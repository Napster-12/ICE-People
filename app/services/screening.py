"""Background checks before the offer (16 Nov 2026, at the user's request; spec IN-008).

Offers were going out without background checks. Now, once HR marks a candidate successful after the interview:

1. HR Admin or the HR Business Partner of the requisition's department starts the checks. The list is the
   "background_checks" setting (HR Admin edits it, one per line), copied onto the candidate's screening.
2. The candidate is emailed a secure link (/background-checks/<token>) to give or refuse consent online: Icebolethu's
   POPIA consent form, digitised (full name, ID number, signed at; kept as a PDF), plus the MIE Personal Credential
   Disclosure Form they download, sign and upload (candidate_forms). Results can't be recorded before consent.
3. HR Admin or the HR BP runs each check with the provider outside the system (no screening provider is connected)
   and records Clear or Adverse once (a recorded result is final and view-only, 16 Nov 2026), the date, the provider's reference, notes (required when Adverse) and the report.
4. The offer can only be sent once every check is Clear (onboarding._deliver calls require_clear). An Adverse result
   or refused consent blocks the offer; HR then marks the candidate unsuccessful (reject), which withdraws any offer
   and sends the requisition back to Interviewing. Results lock once the offer has been sent.
"""
import secrets

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import Application, BackgroundCheck, BackgroundScreening, Department, Job, Requisition
from app.models.user import HR_ADMIN, HRBP
from app.services import audit, files, settings
from app.services.dates import now, today
from app.services.errors import DomainError
from app.services.notifications import notify, render, users_with_role

MANAGE_ROLES = (HR_ADMIN,)                          # plus the HR BP of the requisition's department
REPORT_FILE = "background_check"
CONSENT_FILE = "screening_consent"                  # the signed MIE form and the POPIA consent PDF
REPORT_TYPES = {".pdf", ".jpg", ".jpeg", ".png"}
RESULTS = ("Clear", "Adverse")
CONSENTED = ("In progress", "Clear", "Adverse")     # consent given


# ------------------------------------------------------------------ the list of checks

def checklist():
    return [line.strip() for line in settings.get("background_checks").splitlines() if line.strip()]


def set_checklist(text, user):
    names = []
    for line in (text or "").splitlines():
        name = " ".join(line.split())[:120]
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    if not names:
        raise DomainError("List at least one background check.")
    if len(names) > 15:
        raise DomainError("List 15 background checks at most.")
    value = "\n".join(names)
    if value != settings.get("background_checks"):
        audit.record("config.setting", "setting", "background_checks",
                     before={"value": settings.get("background_checks")}, after={"value": value}, user=user)
        settings.set_value("background_checks", value)
    return names


# ------------------------------------------------------------------ who

def department(application):
    req = application.job.requisition if application.job else None
    return req.department if req is not None else None


def hrbp_for(application):
    dept = department(application)
    user = dept.hrbp if dept is not None else None
    return user if user is not None and user.active and user.has_role(HRBP) else None


def is_hrbp(user, application):
    hrbp = hrbp_for(application)
    return hrbp is not None and hrbp.id == user.id


def can_manage(user, application):
    """HR Admin, or the HR Business Partner of the requisition's department."""
    return user.has_role(*MANAGE_ROLES) or is_hrbp(user, application)


def can_view(user, application):
    from app.services.onboarding import VIEW_ROLES
    return user.has_role(*VIEW_ROLES) or is_hrbp(user, application)


def waiting(user):
    """Candidates who passed the interview and haven't been hired yet (application status Offer), for the
    Onboarding page: all of them for HR, the HR BP's own departments otherwise."""
    from app.services.onboarding import VIEW_ROLES
    q = Application.query.filter(Application.status == "Offer").order_by(Application.successful_at.desc())
    if not user.has_role(*VIEW_ROLES):
        dept_ids = [d.id for d in Department.query.filter_by(hrbp_user_id=user.id).all()]
        q = (q.join(Job, Application.job_id == Job.id).join(Requisition, Job.requisition_id == Requisition.id)
             .filter(Requisition.department_id.in_(dept_ids)))
    return q.all()


def status_of(application):
    screening = application.screening
    return screening.status if screening is not None else "Not started"


def locked(application):
    """Results are final once the offer has gone to the candidate."""
    return any(o.status in ("Sent", "Accepted") for o in application.offers)


# ------------------------------------------------------------------ the offer gate

def problem(application):
    """Why the offer can't be sent yet, or None when every check is Clear."""
    screening = application.screening
    if screening is None:
        return "Run the background checks first: the offer can only be sent once every check is clear."
    if screening.status == "Awaiting consent":
        return "The candidate hasn't consented to the background checks yet, so the offer can't be sent."
    if screening.status == "Consent refused":
        return "The candidate refused consent to the background checks, so the offer can't be sent."
    if screening.status == "Adverse":
        bad = ", ".join(c.name for c in screening.checks if c.status == "Adverse")
        return f"A background check came back adverse ({bad}), so the offer can't be sent."
    outstanding = [c.name for c in screening.checks if c.status != "Clear"]
    if outstanding:
        return "Background checks outstanding: " + ", ".join(outstanding) + "."
    return None


def require_clear(application):
    reason = problem(application)
    if reason:
        raise DomainError(reason)


# ------------------------------------------------------------------ starting and consent

def start(application, user, base_url):
    """Create the candidate's checks from the setting and email the consent link."""
    if not can_manage(user, application):
        raise DomainError("Only HR Admin or the department's HR Business Partner can run the background checks.")
    if application.status != "Offer":
        raise DomainError("Background checks are for a candidate marked successful after the interview.")
    if application.screening is not None:
        raise DomainError("The background checks have already been started.")
    names = checklist()
    if not names:
        raise DomainError("No background checks are set up. HR Admin lists them under Onboarding → Offer letter "
                          "and documents.")
    screening = BackgroundScreening(application=application, status="Awaiting consent", started_by_id=user.id,
                                    checks=[BackgroundCheck(name=n, status="Pending") for n in names])
    db.session.add(screening)
    db.session.flush()
    audit.record("screening.started", "application", application.id, after={"checks": names}, user=user)
    _send_consent(screening, base_url)
    return screening


def resend(screening, user, base_url):
    if not can_manage(user, screening.application):
        raise DomainError("Only HR Admin or the department's HR Business Partner can run the background checks.")
    if screening.status != "Awaiting consent":
        raise DomainError("The candidate has already answered the consent request.")
    _send_consent(screening, base_url)
    audit.record("screening.consent_resent", "application", screening.application_id, user=user)


def _send_consent(screening, base_url):
    application = screening.application
    screening.token = secrets.token_urlsafe(32)
    screening.consent_requested_at = now()
    link = f"{base_url.rstrip('/')}/background-checks/{screening.token}"
    context = {"name": application.candidate.full_name, "title": application.job.title, "ref": application.reference,
               "checks": "\n".join(f"- {c.name}" for c in screening.checks)}
    subject, body = render("candidate_screening_consent", context)
    from app.services.emails import designed
    try:
        get_adapter("email").send_email(application.candidate.email, subject, body,
                                        html=designed("candidate_screening_consent", subject, body, link, context))
    except IntegrationError as exc:
        raise DomainError(f"The consent email to {application.candidate.email} couldn't be sent: {exc}") from exc


def by_token(token):
    return BackgroundScreening.query.filter_by(token=token).first() if token else None


def give_consent(screening, values, mie_upload, ip=None):
    """The candidate's online POPIA consent (Icebolethu's form: full name, ID number, signed at) plus the signed MIE
    Personal Credential Disclosure Form (16 Nov 2026). Both are kept with the checks (CONSENT_FILE)."""
    if screening.status != "Awaiting consent":
        raise DomainError("This consent request has already been answered.")
    typed = " ".join((values.get("full_name") or "").split())[:160]
    id_number = "".join((values.get("id_number") or "").split()).upper()[:20]
    place = " ".join((values.get("place") or "").split())[:120]
    errors = []
    if len(typed) < 3:
        errors.append("Type your full name.")
    if not id_number:
        errors.append("Enter your ID number (or passport number if you're not a South African citizen).")
    elif id_number.isdigit() and len(id_number) == 13:
        from app.services.validators import validate_sa_id
        errors += validate_sa_id(id_number)
    elif not (6 <= len(id_number) <= 20 and id_number.isalnum()):
        errors.append("Enter a 13-digit SA ID number, or your passport number.")
    if len(place) < 2:
        errors.append("Enter where you are signing (town or city).")
    mie = _check_upload(mie_upload, "the signed MIE Personal Credential Disclosure Form")
    if mie is None:
        errors.append("Attach the signed MIE Personal Credential Disclosure Form.")
    if errors:
        raise DomainError(" ".join(errors))
    screening.status, screening.consent_at, screening.consent_name, screening.consent_ip = \
        "In progress", now(), typed, ip
    screening.consent_id_number, screening.consent_place = id_number, place
    screening.token = None
    from app.services import candidate_forms
    files.store_bytes(mie[1], f"MIE consent - {mie[0]}"[:255], CONSENT_FILE, screening.id, check=False)
    files.store_bytes(candidate_forms.popia_pdf(screening), f"POPIA consent {screening.application.reference}.pdf",
                      CONSENT_FILE, screening.id, check=False)
    audit.record("screening.consent_given", "application", screening.application_id,
                 after={"name": typed, "place": place, "ip": ip})
    _notify(screening, "consent given", f"{screening.application.candidate.full_name} consented to the background "
            "checks. Record each check's result as it comes in.")


def _check_upload(upload, label):
    """(filename, bytes) of a PDF/JPG/PNG upload, None when nothing was attached; DomainError when it's wrong."""
    from flask import current_app
    if upload is None or not upload.filename:
        return None
    ext = "." + upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    data = upload.read()
    if ext not in REPORT_TYPES:
        raise DomainError(f"Attach {label} as a PDF, JPG or PNG file.")
    if not data:
        raise DomainError(f"The file for {label} is empty.")
    if len(data) > current_app.config["MAX_UPLOAD_BYTES"]:
        raise DomainError(f"The file for {label} is too large.")
    return upload.filename, data


def consent_files(screening):
    """The signed MIE form and the POPIA consent PDF."""
    return files.files_for(CONSENT_FILE, screening.id)


def refuse_consent(screening, ip=None):
    if screening.status != "Awaiting consent":
        raise DomainError("This consent request has already been answered.")
    screening.status, screening.consent_at, screening.consent_ip, screening.token = "Consent refused", now(), ip, None
    screening.completed_at = now()
    audit.record("screening.consent_refused", "application", screening.application_id, after={"ip": ip})
    _notify(screening, "consent refused", f"{screening.application.candidate.full_name} refused consent to the "
            "background checks, so the offer can't be sent. Mark the candidate unsuccessful from the checks page, "
            "then mark the next-ranked candidate successful on the interview panel or re-advertise.")


# ------------------------------------------------------------------ results

def pending(screening):
    """Checks still waiting for a result. A recorded result is final (16 Nov 2026, at the user's request)."""
    return [c for c in screening.checks if c.status == "Pending"]


def can_record(user, screening):
    return (can_manage(user, screening.application) and screening.status in CONSENTED
            and screening.application.status == "Offer" and not locked(screening.application)
            and bool(pending(screening)))


def record(check, values, report, user):
    """Record a check's result. values: status (Clear/Adverse), completed_on (date), provider_reference, notes;
    report: an optional FileStorage (the provider's report)."""
    screening = check.screening
    if not can_manage(user, screening.application):
        raise DomainError("Only HR Admin or the department's HR Business Partner can record background checks.")
    if screening.status not in CONSENTED:
        raise DomainError("Results can only be recorded once the candidate has consented.")
    if screening.application.status != "Offer" or locked(screening.application):
        raise DomainError("The background checks are closed: the offer has been sent or the candidate is no longer "
                          "waiting for one.")
    if check.status != "Pending":
        raise DomainError(f"{check.name} was already recorded as {check.status.lower()} on "
                          f"{check.recorded_at:%d %b %Y}. A recorded result can't be changed.")
    status = values.get("status")
    completed_on = values.get("completed_on")
    notes = (values.get("notes") or "").strip()[:2000] or None
    errors = []
    if status not in RESULTS:
        errors.append("Choose Clear or Adverse.")
    if completed_on is None:
        errors.append("Enter the date the check was completed.")
    elif completed_on > today():
        errors.append("The completion date can't be in the future.")
    elif screening.consent_at and completed_on < screening.consent_at.date():
        errors.append("The check can't have been completed before the candidate consented.")
    if status == "Adverse" and not notes:
        errors.append("Say what the adverse finding is in the notes.")
    if errors:
        raise DomainError(" ".join(errors))
    before = {"status": check.status, "completed_on": str(check.completed_on or ""), "notes": check.notes}
    if report is not None and report.filename:
        stored = files.save_upload(report, REPORT_FILE, check.id, user=user, allowed=REPORT_TYPES)
        audit.record("screening.report", "application", screening.application_id,
                     after={"check": check.name, "file": stored.original_name}, user=user)
    check.status, check.completed_on, check.notes = status, completed_on, notes
    check.provider_reference = (values.get("provider_reference") or "").strip()[:80] or None
    check.recorded_by_id, check.recorded_at = user.id, now()
    audit.record("screening.result", "application", screening.application_id, before=before,
                 after={"check": check.name, "status": status, "completed_on": str(completed_on), "notes": notes},
                 user=user)
    _refresh(screening)
    return check


def reports(check):
    """Newest first: the first is the current report."""
    return list(reversed(files.files_for(REPORT_FILE, check.id)))


def _refresh(screening):
    statuses = [c.status for c in screening.checks]
    new = "Adverse" if "Adverse" in statuses else "Clear" if statuses and all(s == "Clear" for s in statuses) \
        else "In progress"
    if new == screening.status:
        return
    screening.status = new
    screening.completed_at = now() if new in ("Clear", "Adverse") else None
    name = screening.application.candidate.full_name
    if new == "Clear":
        _notify(screening, "clear", f"Every background check on {name} is clear. HR Admin can now send the offer.")
    elif new == "Adverse":
        bad = ", ".join(c.name for c in screening.checks if c.status == "Adverse")
        _notify(screening, "adverse", f"A background check on {name} came back adverse ({bad}), so the offer can't "
                "be sent. Mark the candidate unsuccessful from the checks page, then mark the next-ranked "
                "candidate successful on the interview panel or re-advertise.")


def _notify(screening, outcome, message):
    application = screening.application
    users = users_with_role(HR_ADMIN) + [hrbp_for(application), screening.started_by]
    notify(users, "screening_update", link=f"/onboarding/checks/{application.id}", outcome=outcome, message=message,
           status=screening.status, name=application.candidate.full_name, title=application.job.title,
           ref=application.reference)


def notify_hrbp(application, decided_by):
    """On the interview decision: the department's HR BP is asked to start the checks."""
    hrbp = hrbp_for(application)
    if hrbp is None:
        return
    dept = department(application)
    notify(hrbp, "screening_needed", link=f"/onboarding/checks/{application.id}",
           name=application.candidate.full_name, title=application.job.title, ref=application.reference,
           department=dept.name if dept else "", decided_by=decided_by.full_name)


# ------------------------------------------------------------------ an adverse result or refused consent

def reject(application, user, reason=""):
    """Mark the candidate unsuccessful after an adverse check or refused consent: any offer in play is withdrawn
    and, with nobody else at offer stage, the requisition goes back to Interviewing."""
    from app.services import onboarding
    from app.models.onboarding import OFFER_OPEN
    if not can_manage(user, application):
        raise DomainError("Only HR Admin or the department's HR Business Partner can do this.")
    screening = application.screening
    if application.status != "Offer" or screening is None or screening.status not in ("Adverse", "Consent refused"):
        raise DomainError("A candidate can only be marked unsuccessful here after an adverse background check or "
                          "refused consent.")
    reason = (reason or "").strip()[:500]
    detail = f"Background checks: {screening.status.lower()}" + (f" ({reason})" if reason else "")
    application.status = "Rejected"
    audit.record("status_change", "application", application.id, before={"status": "Offer"},
                 after={"status": "Rejected"}, detail=detail, user=user)
    for offer in application.offers:
        if offer.status in OFFER_OPEN:
            onboarding.withdraw(offer, user, detail)
    onboarding.requisition_back(application, detail)
    return application
