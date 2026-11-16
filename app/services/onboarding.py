"""Offers and the hand-off to onboarding, owned by HR Admin (8 Nov 2026, at the user's request; spec IN-009, the
§4.5 hand-off, OB-001 and OB-004).

1. HR marks a candidate the panel passed as successful (interviews.mark_successful): application → Offer, HR Admin
   is notified.
2. HR Admin drafts the offer (CTC, start date, employment type, conditions, expiry). An offer above the
   requisition's costed CTC (or for an unbudgeted position) goes to Finance first (workflow type "offer").
3. Sending emails the candidate the offer letter PDF and a secure link (/offer/<token>) to accept or decline.
   It's refused until every background check is Clear (services/screening.py, 16 Nov 2026, at the user's request);
   the offer can be drafted and approved by Finance while the checks run.
4. Acceptance hands off: application Hired, requisition and position Filled, budget consumed, the advert's other
   open applicants "Not selected" (HR sends the regrets), an Employee (Pre-boarding, next employee number) and an
   OnboardingCase.
   The candidate attaches the required onboarding documents (settings "onboarding_documents") to accept
   (10 Nov 2026, at the user's request).
5. Contracts aren't generated (10 Nov 2026, at the user's request): the department's HR Business Partner attaches
   the signed contract to the case.
"""
import re
import secrets
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Application, Department, Employee, Offer, OnboardingCase
from app.models.onboarding import OFFER_EDITABLE, OFFER_OPEN, SALUTATIONS
from app.models.org import EMPLOYMENT_TYPES
from app.models.user import FINANCE, GROUP_HR, HR_ADMIN, HR_MANAGER, HRBP, RECRUITER
from app.services import (audit, budget, careers, documents, files, positions, refs, requisitions, settings,
                          workflow)
from app.services.calendar import add_business_days
from app.services.dates import format_money, now, today
from app.services.errors import DomainError
from app.services.notifications import notify, render, users_with_role

EDIT_ROLES = (HR_ADMIN,)                                    # make offers, run onboarding
VIEW_ROLES = (HR_ADMIN, HR_MANAGER, GROUP_HR)               # see them
OPEN_APPLICATION = ("New", "Screening", "Shortlisted", "Interview", "Offer")
CONTRACT_FILE = "employment_contract"
DOCUMENTS_FILE = "onboarding_document"                     # the candidate's documents, uploaded on acceptance
DOCUMENT_TYPES = {".pdf", ".jpg", ".jpeg", ".png"}
OFFER_FILE = "offer_letter"
EMPLOYEE_PREFIX = "ICE"


# ------------------------------------------------------------------ employee numbers

def next_employee_number():
    """The next ICE number after the highest one on record (ICE1036 → ICE1037). HR Admin may change it."""
    highest = 1000
    for (number,) in db.session.query(Employee.employee_number).all():
        match = re.fullmatch(rf"{EMPLOYEE_PREFIX}(\d+)", number or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{EMPLOYEE_PREFIX}{highest + 1}"


def set_employee_number(employee, number, user):
    number = (number or "").strip().upper()
    if not number:
        raise DomainError("Enter the employee number.")
    if len(number) > 20:
        raise DomainError("The employee number can be 20 characters at most.")
    clash = Employee.query.filter(Employee.employee_number == number, Employee.id != employee.id).first()
    if clash:
        raise DomainError(f"{number} already belongs to {clash.full_name}.")
    if number != employee.employee_number:
        audit.record("employee.number", "employee", employee.id, before={"employee_number": employee.employee_number},
                     after={"employee_number": number}, user=user)
        employee.employee_number = number


# ------------------------------------------------------------------ offers

def can_edit(user):
    return user.has_role(*EDIT_ROLES)


def can_view(user, offer=None):
    if user.has_role(*VIEW_ROLES):
        return True
    if offer is not None and user.has_role(FINANCE):          # Finance sees offers sent to it for approval
        return workflow.latest_instance("offer", offer.id) is not None
    return False


def offers_to_make():
    """Candidates HR marked successful who have no offer in play yet."""
    apps = Application.query.filter_by(status="Offer").order_by(Application.successful_at.desc()).all()
    return [a for a in apps if not any(o.status in OFFER_OPEN + ("Accepted",) for o in a.offers)]


def current_offer(application):
    live = [o for o in application.offers if o.status in OFFER_OPEN + ("Accepted",)]
    return live[-1] if live else None


def costed_ctc(application):
    req = application.job.requisition if application.job else None
    if req is not None and req.ctc is not None:
        return Decimal(req.ctc)
    return None


def draft(application, user):
    """A new offer, filled in from the requisition and position."""
    if application.status != "Offer":
        raise DomainError("Only a candidate marked successful after the interview can get an offer.")
    if current_offer(application):
        raise DomainError("This candidate already has an offer in progress.")
    req = application.job.requisition if application.job else None
    position = req.approved_position if req else None
    start = req.required_start_date if req and req.required_start_date and req.required_start_date > today() \
        else add_business_days(today(), 20)
    ctc = costed_ctc(application) or (Decimal(position.budgeted_ctc) if position and position.budgeted_ctc else None)
    offer = Offer(reference=refs.next_reference("OFR"), application=application, status="Draft",
                  ctc=ctc or Decimal("0.00"), start_date=start,
                  employment_type=(req.employment_type if req and req.employment_type in EMPLOYMENT_TYPES
                                   else "Permanent"),
                  contract_end_date=req.contract_end_date if req else None,
                  expires_on=add_business_days(today(), 5), created_by_id=user.id,
                  work_location=(position.branch.name if position and position.branch else None)
                  or (application.job.location if application.job else None),
                  candidate_address=careers.address_lines(application.candidate) or application.candidate.location
                  or None,
                  salutation=application.candidate.title if application.candidate.title in SALUTATIONS else None)
    offer.probation_months = settings.get("probation_months", int) if offer.employment_type == "Permanent" else None
    db.session.add(offer)
    db.session.flush()
    offer.needs_approval = needs_approval(offer)
    audit.record("create", "offer", offer.id, after={"ref": offer.reference, "candidate": offer.candidate.full_name},
                 user=user)
    return offer


def needs_approval(offer):
    """Finance approves an offer above the requisition's costed CTC, or any offer without one (spec IN-009)."""
    costed = costed_ctc(offer.application)
    return costed is None or Decimal(offer.ctc or 0) > costed


def parse(values):
    """Form values → clean fields, or DomainError."""
    from datetime import date
    errors, out = [], {}
    try:
        out["ctc"] = Decimal(str(values.get("ctc", "")).replace(" ", "").replace(",", "").replace("R", "") or "x")
        if out["ctc"] <= 0:
            raise InvalidOperation
        out["ctc"] = out["ctc"].quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        errors.append("Enter the annual cost to company as an amount, e.g. 360000.")
    for key, label in (("start_date", "start date"), ("expires_on", "date the offer expires"),
                       ("contract_end_date", "contract end date")):
        raw = (values.get(key) or "").strip()
        if not raw:
            out[key] = None
            continue
        try:
            out[key] = date.fromisoformat(raw)
        except ValueError:
            errors.append(f"Enter the {label} as a date.")
    out["employment_type"] = values.get("employment_type") or ""
    if out["employment_type"] not in EMPLOYMENT_TYPES:
        errors.append("Choose the employment type.")
    out["conditions"] = (values.get("conditions") or "").strip() or None
    out["salutation"] = (values.get("salutation") or "").strip() or None
    if out["salutation"] and out["salutation"] not in SALUTATIONS:
        errors.append("Choose Mr, Ms, Mrs, Dr or Prof, or leave the salutation blank.")
    out["candidate_address"] = "\n".join(l.strip() for l in (values.get("candidate_address") or "").splitlines()
                                         if l.strip())[:500] or None
    out["work_location"] = (values.get("work_location") or "").strip()[:255] or None
    raw = str(values.get("probation_months") or "").strip()
    try:
        out["probation_months"] = int(raw) if raw else None
        if out["probation_months"] is not None and not 0 <= out["probation_months"] <= 12:
            raise ValueError
        out["probation_months"] = out["probation_months"] or None
    except ValueError:
        errors.append("The probation period is 0 to 12 months.")
    if not errors:
        if not out["start_date"]:
            errors.append("Enter the start date.")
        elif out["start_date"] < today():
            errors.append("The start date can't be in the past.")
        if not out["expires_on"]:
            errors.append("Enter the date the offer expires.")
        elif out["expires_on"] < today():
            errors.append("The offer can't expire in the past.")
        elif out["start_date"] and out["expires_on"] >= out["start_date"]:
            errors.append("The offer must expire before the start date.")
        if out["employment_type"] == "Contract":
            if not out["contract_end_date"]:
                errors.append("A contract offer needs the contract end date.")
            elif out["start_date"] and out["contract_end_date"] <= out["start_date"]:
                errors.append("The contract must end after it starts.")
        else:
            out["contract_end_date"] = None
    if errors:
        raise DomainError(" ".join(errors))
    return out


def save(offer, values, user):
    if offer.status not in OFFER_EDITABLE:
        raise DomainError(f"A {offer.status.lower()} offer can't be changed.")
    clean = parse(values)
    before = {k: str(getattr(offer, k)) for k in clean}
    for key, value in clean.items():
        setattr(offer, key, value)
    offer.needs_approval = needs_approval(offer)
    b, a = audit.changes(before, {k: str(getattr(offer, k)) for k in clean})
    audit.record("update", "offer", offer.id, before=b, after=a, user=user)
    return offer


def conditions_list(offer):
    return [line.strip(" -•\t") for line in (offer.conditions or "").splitlines() if line.strip(" -•\t")]


def _reports_to(position):
    """"Group ICT Manager, Tinashe Chadamoyo", as in the current offer letter."""
    boss = position.reports_to if position else None
    if boss is None:
        return ""
    holder = boss.holder
    return f"{boss.title}, {holder.full_name}" if holder else boss.title


EMPLOYMENT = {"Permanent": "Permanent Employment", "Contract": "Fixed-term Employment", "Casual": "Casual Employment"}


def letter_context(offer):
    req = offer.requisition
    position = req.approved_position if req else None
    ctc = Decimal(offer.ctc or 0)
    return {"today": documents.long_date(today()), "name": offer.candidate.full_name, "ref": offer.reference,
            "title": offer.job.title if offer.job else "", "department": req.department.name if req and req.department
            else "", "reports_to": _reports_to(position),
            "grade": req.job_grade.name if req and req.job_grade else "", "employment_type": offer.employment_type,
            "start_date": documents.long_date(offer.start_date), "end_date": documents.long_date(offer.contract_end_date)
            if offer.contract_end_date else "", "ctc": format_money(ctc), "monthly": format_money(ctc / 12),
            "conditions": conditions_list(offer), "expires_on": documents.long_date(offer.expires_on),
            "salutation": offer.salutation or "", "address": offer.candidate_address or "",
            "location": offer.work_location or "", "employment": EMPLOYMENT.get(offer.employment_type, "Employment"),
            "probation": documents.probation_words(offer.probation_months),
            "accepted_by": offer.candidate.full_name if offer.status == "Accepted" else "",
            "accepted_on": documents.long_datetime(offer.responded_at) if offer.status == "Accepted" and offer.responded_at
            else ""}


def letter_pdf(offer):
    title, body = documents.render("offer_letter", letter_context(offer))
    return documents.pdf(title, body, ref=offer.reference)


def _description(offer):
    return {"ref": offer.reference, "title": f"Offer: {offer.candidate.full_name}, {offer.job.title}",
            "link": f"/onboarding/offers/{offer.id}"}


def send(offer, user, base_url):
    """Send the offer, or put it to Finance first when it needs approval. Returns "sent" or "approval"."""
    if offer.status in OFFER_EDITABLE:
        parse({"ctc": offer.ctc, "start_date": offer.start_date and offer.start_date.isoformat(),
               "expires_on": offer.expires_on and offer.expires_on.isoformat(),
               "contract_end_date": offer.contract_end_date and offer.contract_end_date.isoformat(),
               "employment_type": offer.employment_type, "conditions": offer.conditions})
        offer.needs_approval = needs_approval(offer)
        if offer.needs_approval:
            req = offer.requisition
            offer.status = "In Approval"
            audit.record("status_change", "offer", offer.id, before={"status": "Draft"},
                         after={"status": "In Approval"}, user=user)
            workflow.start("offer", "offer", offer.id, user, context=_context(offer),
                           department=req.department if req else None)
            if offer.status == "In Approval":
                return "approval"
            from app.services import screening
            if screening.problem(offer.application):       # approved at once, but the checks aren't clear yet
                return "approved"
            return _deliver(offer, user, base_url)
        return _deliver(offer, user, base_url)
    if offer.status == "Approved":
        return _deliver(offer, user, base_url)
    raise DomainError(f"A {offer.status.lower()} offer can't be sent.")


def _context(offer):
    req = offer.requisition
    costed = costed_ctc(offer.application)
    return {"department_id": req.department_id if req else None,
            "grade": req.job_grade.grade if req and req.job_grade else 0,
            "employment_type": offer.employment_type, "ctc": float(offer.ctc or 0),
            "over_by": float(Decimal(offer.ctc) - costed) if costed is not None else float(offer.ctc or 0)}


def _deliver(offer, user, base_url):
    from app.services import screening
    screening.require_clear(offer.application)        # background checks first (16 Nov 2026)
    pdf = letter_pdf(offer)
    stored = files.store_bytes(pdf, f"{offer.reference} offer letter.pdf", OFFER_FILE, offer.id, user=user,
                               check=False)
    offer.letter_file = stored
    offer.token = secrets.token_urlsafe(32)
    link = f"{base_url.rstrip('/')}/offer/{offer.token}"
    context = {"name": offer.candidate.full_name, "title": offer.job.title, "ref": offer.reference,
               "expires_on": documents.long_date(offer.expires_on), "start_date": documents.long_date(offer.start_date)}
    subject, body = render("candidate_offer", context)
    from app.services.emails import designed
    try:
        get_adapter("email").send_email(offer.candidate.email, subject, body,
                                        html=designed("candidate_offer", subject, body, link, context),
                                        attachments=[(f"{offer.reference} offer letter.pdf", pdf, "application/pdf")])
    except IntegrationError as exc:
        raise DomainError(f"The offer email to {offer.candidate.email} couldn't be sent: {exc}") from exc
    old = offer.status
    offer.status, offer.sent_at = "Sent", now()
    audit.record("status_change", "offer", offer.id, before={"status": old}, after={"status": "Sent"},
                 detail=f"Emailed to {offer.candidate.email}", user=user)
    return "sent"


def withdraw(offer, user, reason=""):
    if offer.status not in OFFER_OPEN:
        raise DomainError(f"A {offer.status.lower()} offer can't be withdrawn.")
    instance = workflow.latest_instance("offer", offer.id)
    if instance is not None and instance.status == "Pending":
        workflow.cancel(instance)
    old = offer.status
    offer.status, offer.token = "Withdrawn", None
    audit.record("status_change", "offer", offer.id, before={"status": old}, after={"status": "Withdrawn"},
                 detail=reason or None, user=user)
    _back_to_interviewing(offer)


def _back_to_interviewing(offer):
    """No offer left in play for the requisition: it goes back to Interviewing."""
    requisition_back(offer.application, f"{offer.reference} {offer.status.lower()}")


def requisition_back(application, comment):
    """With nobody else at offer stage, the requisition goes back from Offer to Interviewing."""
    job = application.job
    req = job.requisition if job else None
    if req is None or req.status != "Offer":
        return
    others = [a for a in job.applications if a.status == "Offer" and a.id != application.id]
    if not others:
        requisitions.set_status(req, "Interviewing", comment=comment, notify_originator=False)


# ------------------------------------------------------------------ the candidate's answer

def by_token(token):
    return Offer.query.filter_by(token=token).first() if token else None


def expire_if_due(offer):
    if offer.status == "Sent" and offer.expires_on < today():
        offer.status = "Expired"
        audit.record("status_change", "offer", offer.id, before={"status": "Sent"}, after={"status": "Expired"},
                     detail="Not answered in time")
        _notify_team(offer, "offer_declined", outcome="expired", reason="The candidate didn't answer in time.")
        _back_to_interviewing(offer)
        return True
    return False


def expire_all():
    """Daily: offers past their expiry date lapse (flask expire-offers)."""
    return sum(1 for o in Offer.query.filter_by(status="Sent").all() if expire_if_due(o))


def _team(offer):
    users = users_with_role(HR_ADMIN) + users_with_role(RECRUITER)
    if offer.created_by:
        users.append(offer.created_by)
    return users


def _notify_team(offer, key, **extra):
    notify(_team(offer), key, link=f"/onboarding/offers/{offer.id}", ref=offer.reference,
           name=offer.candidate.full_name, title=offer.job.title, **extra)


def decline(offer, reason, ip=None):
    if expire_if_due(offer) or offer.status != "Sent":
        raise DomainError("This offer can no longer be answered.")
    offer.status, offer.responded_at, offer.response_ip = "Declined", now(), ip
    offer.decline_reason = (reason or "").strip()[:2000] or None
    offer.application.status = "Rejected"
    audit.record("status_change", "offer", offer.id, before={"status": "Sent"}, after={"status": "Declined"},
                 detail=offer.decline_reason)
    _notify_team(offer, "offer_declined", outcome="declined", reason=offer.decline_reason or "No reason given.")
    _back_to_interviewing(offer)


def required_documents():
    """The documents a candidate must attach to accept an offer (HR Admin edits the list, one per line)."""
    return [line.strip() for line in settings.get("onboarding_documents").splitlines() if line.strip()]


def set_required_documents(text, user):
    names = []
    for line in (text or "").splitlines():
        name = " ".join(line.split())[:120]
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    if len(names) > 20:
        raise DomainError("List 20 documents at most.")
    value = "\n".join(names)
    if value != settings.get("onboarding_documents"):
        audit.record("config.setting", "setting", "onboarding_documents",
                     before={"value": settings.get("onboarding_documents")}, after={"value": value}, user=user)
        settings.set_value("onboarding_documents", value)
    return names


# Words that don't tell documents apart: "ID copy" is the application's "ID copy", "Highest qualification" its
# "Highest qualification certificate", "Updated CV" the CV.
_DOC_NOISE = {"copy", "of", "your", "the", "a", "an", "certificate", "certified", "document", "documents", "updated",
              "recent", "latest", "sars"}


def _doc_words(name):
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if w not in _DOC_NOISE}


def already_submitted(candidate):
    """The required onboarding documents the candidate already sent with their application (16 Nov 2026, at the
    user's request: don't ask for them again). {document name: StoredFile}."""
    from app.services import careers
    sent = careers.candidate_documents(candidate) if candidate is not None else []
    found = {}
    for name in required_documents():
        words = _doc_words(name)
        if not words:
            continue
        if words == {"cv"} and candidate.cv_file is not None:
            found[name] = candidate.cv_file
            continue
        for sent_name, stored in sent:
            theirs = _doc_words(sent_name)
            if theirs and (words <= theirs or theirs <= words):
                found[name] = stored
                break
    return found


def check_documents(uploads, have=None):
    """uploads: {document name: FileStorage}. Returns [(name, filename, bytes)] for every required document, or
    raises DomainError listing what's missing or wrong. Checked before anything changes. have: documents already
    received with the application (already_submitted); they're not needed again, but a newer one may be attached."""
    from flask import current_app
    limit = current_app.config["MAX_UPLOAD_BYTES"]
    ready, missing, problems = [], [], []
    for name in required_documents():
        upload = (uploads or {}).get(name)
        if upload is None or not upload.filename:
            if name not in (have or {}):
                missing.append(name)
            continue
        ext = "." + upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        data = upload.read()
        if ext not in DOCUMENT_TYPES:
            problems.append(f"{name} must be a PDF, JPG or PNG file.")
        elif not data:
            problems.append(f"The file for {name} is empty.")
        elif len(data) > limit:
            problems.append(f"{name} is larger than {limit // (1024 * 1024)} MB.")
        else:
            ready.append((name, upload.filename, data))
    if missing:
        problems.insert(0, "Attach " + ", ".join(missing) + " to accept the offer.")
    if problems:
        raise DomainError(" ".join(problems))
    return ready


def _store_documents(case, ready):
    for name, filename, data in ready:
        files.store_bytes(data, f"{name} - {filename}"[:255], DOCUMENTS_FILE, case.id, check=False)
    if ready:
        audit.record("onboarding.documents", "onboarding_case", case.id, after={"documents": [n for n, _f, _d in ready]})


def case_documents(case):
    return files.files_for(DOCUMENTS_FILE, case.id)


def accept(offer, ip=None, uploads=None, code_of_conduct=False, base_url=""):
    """The candidate accepts, attaching the required documents and accepting the Code of Conduct (16 Nov 2026):
    hand off to onboarding. Returns the new OnboardingCase, whose new starter pack link is in the welcome email."""
    if expire_if_due(offer) or offer.status != "Sent":
        raise DomainError("This offer can no longer be answered.")
    if not code_of_conduct:
        raise DomainError("Read the Icebolethu Group Code of Conduct and tick the box to accept it.")
    have = already_submitted(offer.candidate)
    ready = check_documents(uploads, have)
    uploaded_now = {name for name, _f, _d in ready}
    ready += [(name, stored.original_name, files.read(stored)) for name, stored in have.items()
              if name not in uploaded_now]                    # copied onto the case from the application
    offer.code_of_conduct_at = now()
    application, job, req = offer.application, offer.job, offer.requisition
    offer.status, offer.responded_at, offer.response_ip = "Accepted", now(), ip
    audit.record("status_change", "offer", offer.id, before={"status": "Sent"}, after={"status": "Accepted"})
    # Keep the letter as accepted: its acceptance section now shows who accepted and when.
    offer.accepted_file = files.store_bytes(letter_pdf(offer), f"{offer.reference} offer letter (accepted).pdf",
                                            OFFER_FILE, offer.id, check=False)
    application.status = "Hired"
    audit.record("status_change", "application", application.id, before={"status": "Offer"},
                 after={"status": "Hired"}, detail=f"{offer.reference} accepted")

    # The rest of the advert's applicants are not selected; HR sends them the regret letter.
    for other in job.applications:
        if other.id != application.id and other.status in OPEN_APPLICATION:
            for o in other.offers:
                if o.status in OFFER_OPEN:
                    o.status, o.token = "Withdrawn", None
            audit.record("status_change", "application", other.id, before={"status": other.status},
                         after={"status": "Not selected"}, detail=f"Position filled ({offer.reference})")
            other.status = "Not selected"

    position = req.approved_position if req else None
    if req is not None:
        if req.status == "Offer":
            requisitions.set_status(req, "Filled", comment=f"{offer.candidate.full_name} accepted {offer.reference}")
            req.closed_at = now()
        if req.ctc is not None and Decimal(req.committed_amount or 0) > 0:
            budget.consume(req, offer.ctc)
    if job is not None and job.status == "Open":
        from app.services import adverts
        adverts.close(job, f"Position filled: {offer.candidate.full_name} accepted the offer")

    employee = _new_employee(offer, position, req)
    case = OnboardingCase(reference=refs.next_reference("ONB"), employee=employee, application=application,
                          offer=offer, start_date=offer.start_date, status="Pre-boarding")
    db.session.add(case)
    db.session.flush()
    audit.record("create", "onboarding_case", case.id, after={"ref": case.reference, "employee":
                 employee.employee_number, "start_date": str(case.start_date)})
    _store_documents(case, ready)
    from app.services import starter_pack
    pack = starter_pack.create(case)

    _notify_team(offer, "offer_accepted", start_date=documents.long_date(offer.start_date),
                 employee_number=employee.employee_number)
    hrbp = hrbp_for(case)
    if hrbp is not None:
        notify(hrbp, "contract_needed", link=f"/onboarding/cases/{case.id}", ref=case.reference,
               name=employee.full_name, title=offer.job.title, start_date=documents.long_date(case.start_date),
               department=employee.department.name if employee.department else "")
    notify_candidate(offer, "candidate_offer_accepted", link=starter_pack.link(pack, base_url) if base_url else None)
    return case


def _new_employee(offer, position, req):
    cand = offer.candidate
    parts = cand.full_name.split()
    manager = position.reports_to.holder if position and position.reports_to else None
    ee = {k: getattr(cand, k) for k in ("gender", "race", "disability")
          if getattr(cand, k) and getattr(cand, k) != careers.PREFER_NOT}       # from the application (16 Nov 2026)
    employee = Employee(employee_number=next_employee_number(),
                        first_name=cand.first_names or (parts[0] if parts else "New"),
                        last_name=cand.surname or " ".join(parts[1:]) or "-", email=cand.email,
                        phone=cand.phone, id_number=cand.id_number, date_of_birth=cand.date_of_birth, **ee,
                        department_id=req.department_id if req else None,
                        cost_centre_id=req.cost_centre_id if req else None,
                        job_grade_id=req.job_grade_id if req else None,
                        approved_position_id=position.id if position else None,
                        position_title=offer.job.title, manager_id=manager.id if manager else None,
                        start_date=offer.start_date, end_date=offer.contract_end_date,
                        employment_type=offer.employment_type, status="Pre-boarding")
    db.session.add(employee)
    db.session.flush()
    audit.record("create", "employee", employee.id, after={"employee_number": employee.employee_number,
                 "name": employee.full_name, "status": "Pre-boarding"}, detail=f"From {offer.reference}")
    if position is not None:
        positions.employee_changed(employee)
    return employee


def notify_candidate(offer, key, link=None):
    context = {"name": offer.candidate.full_name, "title": offer.job.title, "ref": offer.reference,
               "start_date": documents.long_date(offer.start_date)}
    subject, body = render(key, context)
    from app.services.emails import designed
    try:
        get_adapter("email").send_email(offer.candidate.email, subject, body,
                                        html=designed(key, subject, body, link, context=context))
    except IntegrationError:
        pass                                                   # logged in the Integration Log


# ------------------------------------------------------------------ onboarding cases and contracts

def hrbp_for(case):
    """The HR Business Partner of the new starter's department (attaches the signed contract)."""
    dept = case.employee.department
    user = dept.hrbp if dept is not None else None
    return user if user is not None and user.active and user.has_role(HRBP) else None


def is_case_hrbp(user, case):
    hrbp = hrbp_for(case)
    return hrbp is not None and hrbp.id == user.id


def can_view_case(user, case):
    return user.has_role(*VIEW_ROLES) or is_case_hrbp(user, case)


def can_attach_contract(user, case):
    return is_case_hrbp(user, case) and case.status != "Cancelled"


def cases(user=None):
    q = OnboardingCase.query.order_by(OnboardingCase.start_date)
    if user is not None and not user.has_role(*VIEW_ROLES):        # an HR BP: their departments' new starters
        dept_ids = [d.id for d in Department.query.filter_by(hrbp_user_id=user.id).all()]
        q = q.join(Employee, OnboardingCase.employee_id == Employee.id).filter(Employee.department_id.in_(dept_ids))
    return q.all()


def upload_signed(case, file_storage, signed_on, user):
    """Contracts aren't generated: the department's HR BP attaches the signed contract (10 Nov 2026)."""
    if not can_attach_contract(user, case):
        raise DomainError("Only the department's HR Business Partner can attach the contract.")
    if file_storage is None or not file_storage.filename:
        raise DomainError("Choose the signed contract to upload.")
    if signed_on is None:
        raise DomainError("Enter the date the contract was signed.")
    if signed_on > today():
        raise DomainError("The signing date can't be in the future.")
    stored = files.save_upload(file_storage, CONTRACT_FILE, case.id, user=user, allowed=DOCUMENT_TYPES)
    case.contract_status, case.contract_signed_on = "Signed", signed_on
    audit.record("contract.signed", "onboarding_case", case.id, after={"file": stored.original_name,
                 "signed_on": str(signed_on)}, user=user)
    return stored


def signed_copies(case):
    """Newest first: the first is the current signed contract."""
    return list(reversed(files.files_for(CONTRACT_FILE, case.id)))


# ------------------------------------------------------------------ workflow handlers

def _offer(instance):
    return db.session.get(Offer, instance.entity_id)


def _on_approved(instance):
    offer = _offer(instance)
    offer.status = "Approved"
    audit.record("status_change", "offer", offer.id, before={"status": "In Approval"}, after={"status": "Approved"})


def _on_returned(instance):
    _offer(instance).status = "Returned"


def _on_rejected(instance):
    offer = _offer(instance)
    offer.status = "Rejected"
    _back_to_interviewing(offer)


workflow.register("offer", describe=lambda i: _description(_offer(i)), on_approved=_on_approved,
                  on_returned=_on_returned, on_rejected=_on_rejected,
                  sample_context={"department_id": 1, "grade": 3, "employment_type": "Permanent", "ctc": 360000.0,
                                  "over_by": 20000.0})
