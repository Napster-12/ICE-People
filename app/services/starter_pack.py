"""The new starter pack (16 Nov 2026, at the user's request).

On offer acceptance the candidate's welcome email carries a secure link (/new-starter/<token>) to:
- the New Hire Take-On form, digitised (Icebolethu's form: biographical details, addresses, next of kin, nomination
  of beneficiary, employment equity declaration, tax and banking details), saved as they go and then submitted;
- the Business and Financial Disclosure Form (completed before a Commissioner of Oaths) and the Liberty Nomination of
  Beneficiary Form, downloaded, completed and uploaded (candidate_forms); and optional supporting documents.

HR Admin or the department's HR Business Partner reviews the submission on the onboarding case: Return (with a comment, emailed
to the candidate, who corrects and resubmits) or Approve, which updates the employee record (names, ID number, date of
birth, cell number, gender, race, disability, bank account). The answers stay on the pack, encrypted.
"""
import json
import re
import secrets
from datetime import date

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import NewStarterPack
from app.models.user import HR_ADMIN
from app.services import audit, documents, files
from app.services.dates import now
from app.services.errors import DomainError
from app.services.notifications import notify, render, users_with_role

FILE = "starter_pack"
TYPES = {".pdf", ".jpg", ".jpeg", ".png"}
EDITABLE = ("Not started", "In progress", "Returned")

TITLES = ["Mr", "Ms", "Mrs", "Miss", "Dr", "Prof"]
YES_NO = ["No", "Yes"]
MARITAL = ["Single", "Married", "Divorced", "Widowed", "Life partner"]
GENDERS = ["Male", "Female"]
RACES = ["African", "Coloured", "Indian", "White"]
ACCOUNT_TYPES = ["Savings", "Cheque / Current", "Transmission"]


def F(key, label, kind="text", required=False, options=None, hint=None):
    return {"key": key, "label": label, "kind": kind, "required": required, "options": options or [], "hint": hint}


# The New Hire Take-On form, section by section (labels as on Icebolethu's form).
SECTIONS = [
    ("Biographical details", None, [
        F("title", "Title", "choice", True, TITLES),
        F("surname", "Surname", required=True),
        F("first_names", "First names", required=True),
        F("middle_names", "Middle names"),
        F("preferred_name", "Preferred name"),
        F("date_of_birth", "Date of birth", "date", True),
        F("sa_citizen", "South African citizen", "choice", True, ["Yes", "No"]),
        F("id_number", "SA ID number", hint="Required for South African citizens."),
        F("other_nationality", "Other nationality", hint="If you're not a South African citizen."),
        F("passport_number", "Passport number", hint="For non-South African citizens."),
        F("passport_expiry", "Passport expiry date", "date"),
        F("permit_expiry", "Work permit expiry date", "date"),
        F("marital_status", "Marital status", "choice", True, MARITAL),
        F("children", "Number of children", "number", True),
        F("qualification", "Highest qualification", required=True),
        F("debarred", "Debarment status", "choice", True, YES_NO, "Have you been debarred (e.g. by the FSCA)?"),
        F("debarment_reason", "Reason for debarment", "textarea", hint="Only if you were debarred."),
    ]),
    ("Permanent residence", None, [
        F("res_street", "House number and street", required=True),
        F("res_suburb", "Suburb or district", required=True),
        F("res_city", "City or town", required=True),
        F("res_code", "Postal code", required=True),
        F("res_phone", "Telephone number"),
        F("cell", "Cellular number", required=True),
    ]),
    ("Postal address", "Leave blank if it's the same as your residence.", [
        F("post_unit", "Unit or postal number"),
        F("post_street", "Street number and name"),
        F("post_city", "City"),
        F("post_code", "Postal code"),
    ]),
    ("Emergency address", "An address other than your own residence.", [
        F("em_street", "House number and street", required=True),
        F("em_suburb", "Suburb or district", required=True),
        F("em_city", "City", required=True),
        F("em_code", "Postal code", required=True),
    ]),
    ("Next of kin", None, [
        F("kin_name", "Name", required=True),
        F("kin_relationship", "Relationship", required=True),
        F("kin_phone", "Telephone number", required=True),
    ]),
    ("Nomination of beneficiary", "Who should receive your pro-rata salary, leave payout and pro-rata bonus in the "
                                  "event of your death.", [
        F("ben_title", "Title", "choice", False, TITLES),
        F("ben_initials", "Initials"),
        F("ben_names", "Full names", required=True),
        F("ben_surname", "Surname", required=True),
        F("ben_dob", "Date of birth", "date"),
        F("ben_id", "ID or passport number"),
        F("ben_physical", "Physical address", "textarea", True),
        F("ben_postal", "Postal address", "textarea"),
        F("ben_work", "Work number"),
        F("ben_home", "Home number"),
        F("ben_cell", "Cell number", required=True),
        F("ben_email", "Email address"),
    ]),
    ("Employment equity declaration", "Confidential. Used only to comply with the Employment Equity Act, 55 of 1998. "
                                      "People with disabilities have the right not to disclose their disability.", [
        F("gender", "Gender", "choice", True, GENDERS),
        F("race", "Race", "choice", True, RACES),
        F("foreign_national", "Foreign national", "choice", True, YES_NO),
        F("citizenship_date", "Date citizenship acquired", "date", hint="If you're not a citizen by birth."),
        F("disability", "Person with a disability", "choice", True, YES_NO),
        F("disability_nature", "Nature of disability", "textarea", hint="Optional."),
    ]),
    ("Tax information", None, [
        F("tax_office", "Tax office"),
        F("tax_number", "Tax number", required=True, hint="Your 10-digit SARS income tax number."),
    ]),
    ("Banking details", "Your bank confirmation letter was attached when you accepted the offer.", [
        F("account_holder", "Account holder", required=True),
        F("bank_name", "Bank name", required=True),
        F("branch_code", "Branch code", required=True),
        F("account_number", "Account number", required=True),
        F("account_type", "Account type", "choice", True, ACCOUNT_TYPES),
    ]),
]
FIELDS = {f["key"]: f for _t, _h, fields in SECTIONS for f in fields}

# Documents: the downloadable forms (required) and supporting documents from the form's section 8 (optional).
DOCUMENTS = [
    ("disclosure", "Business and Financial Disclosure Form (sworn before a Commissioner of Oaths)", True),
    ("liberty", "Liberty Nomination of Beneficiary Form", True),
    ("drivers_licence", "Driver's licence (if applicable)", False),
    ("marriage_certificate", "Marriage certificate (if married)", False),
    ("spouse_id", "Copy of your spouse's ID (if married)", False),
    ("children_certificates", "Children's birth certificates or IDs", False),
]
DOC_LABELS = {k: label for k, label, _r in DOCUMENTS}


# ------------------------------------------------------------------ create and read

def create(case):
    """On acceptance: a pack with its secure link. Returns it."""
    pack = NewStarterPack(case=case, status="Not started", token=secrets.token_urlsafe(32), uploads={})
    db.session.add(pack)
    db.session.flush()
    return pack


def by_token(token):
    return NewStarterPack.query.filter_by(token=token).first() if token else None


def link(pack, base_url):
    return f"{base_url.rstrip('/')}/new-starter/{pack.token}" if pack.token else None


def answers(pack):
    try:
        return json.loads(pack.data) if pack.data else {}
    except ValueError:
        return {}


def prefill(pack):
    """First visit: names, ID, date of birth and cell from what we already have."""
    emp = pack.case.employee
    screening = pack.case.application.screening if pack.case.application else None
    out = {"first_names": emp.first_name, "surname": emp.last_name if emp.last_name != "-" else "",
           "cell": emp.phone or "", "sa_citizen": "Yes"}
    if pack.case.offer and pack.case.offer.salutation in TITLES:
        out["title"] = pack.case.offer.salutation
    cand = pack.case.application.candidate if pack.case.application else None
    if cand is not None:                                     # the application's profile (16 Nov 2026)
        for key, value in (("title", cand.title), ("first_names", cand.first_names), ("surname", cand.surname),
                           ("date_of_birth", cand.date_of_birth and cand.date_of_birth.isoformat()),
                           ("sa_citizen", cand.sa_citizen), ("res_street", cand.street), ("res_suburb", cand.suburb),
                           ("res_city", cand.city), ("res_code", cand.postal_code), ("cell", cand.phone),
                           ("res_phone", cand.alt_phone)):
            if value:
                out[key] = value
        if cand.sa_citizen == "No":
            out.update({"other_nationality": cand.nationality or "", "passport_number": cand.id_number or "",
                        "permit_expiry": cand.work_permit_expiry.isoformat() if cand.work_permit_expiry else ""})
        elif cand.id_number:
            out["id_number"] = cand.id_number
        for key, options in (("gender", GENDERS), ("race", RACES)):
            if getattr(cand, key) in options:
                out[key] = getattr(cand, key)
        if cand.disability in YES_NO:
            out["disability"] = cand.disability
    if screening is not None and screening.consent_id_number:
        number = screening.consent_id_number
        if number.isdigit() and len(number) == 13:
            out["id_number"] = number
        else:
            out.update({"sa_citizen": "No", "passport_number": number})
    return out


def uploaded(pack):
    """{document key: StoredFile} for the pack's current uploads."""
    from app.models import StoredFile
    out = {}
    for key, file_id in (pack.uploads or {}).items():
        stored = db.session.get(StoredFile, file_id)
        if stored is not None:
            out[key] = stored
    return out


# ------------------------------------------------------------------ the candidate fills it in

def _clean(values):
    out = {}
    for key, field in FIELDS.items():
        value = (values.get(key) or "").strip()
        value = value[:600] if field["kind"] == "textarea" else " ".join(value.split())[:160]
        if value:
            out[key] = value
    return out


def _store_uploads(pack, uploads):
    from app.services.screening import _check_upload
    current = dict(pack.uploads or {})
    for key, label, _required in DOCUMENTS:
        got = _check_upload((uploads or {}).get(key), label)
        if got is None:
            continue
        stored = files.store_bytes(got[1], f"{label.split(' (')[0]} - {got[0]}"[:255], FILE, pack.id, check=False)
        current[key] = stored.id
    pack.uploads = current


def save(pack, values, uploads):
    """Keep what's been typed so far (no checks), and any files attached."""
    if pack.status not in EDITABLE:
        raise DomainError("Your new starter pack has been submitted and can't be changed.")
    pack.data = json.dumps(_clean(values))
    _store_uploads(pack, uploads)
    if pack.status == "Not started":
        pack.status = "In progress"


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def problems(data, uploaded_keys):
    """What's missing or wrong before the pack can be submitted."""
    out = []
    for key, field in FIELDS.items():
        value = data.get(key, "")
        if field["required"] and not value:
            out.append(f"{field['label']} is required.")
        elif value and field["kind"] == "date" and _date(value) is None:
            out.append(f"{field['label']} must be a date.")
        elif value and field["kind"] == "choice" and value not in field["options"]:
            out.append(f"Choose an option for {field['label'].lower()}.")
    if data.get("children") and not (data["children"].isdigit() and int(data["children"]) <= 30):
        out.append("Number of children must be a whole number.")
    dob = _date(data.get("date_of_birth"))
    if data.get("sa_citizen") == "Yes":
        if not data.get("id_number"):
            out.append("Enter your SA ID number.")
        else:
            from app.services.validators import validate_sa_id
            out += validate_sa_id(data["id_number"], dob)
    elif data.get("sa_citizen") == "No":
        for key in ("other_nationality", "passport_number", "passport_expiry", "permit_expiry"):
            if not data.get(key):
                out.append(f"{FIELDS[key]['label']} is required if you're not a South African citizen.")
    if data.get("debarred") == "Yes" and not data.get("debarment_reason"):
        out.append("Give the reason for your debarment.")
    if data.get("tax_number") and not re.fullmatch(r"\d{10}", data["tax_number"].replace(" ", "")):
        out.append("The tax number has 10 digits.")
    if data.get("branch_code") and not re.fullmatch(r"\d{4,6}", data["branch_code"].replace(" ", "")):
        out.append("The branch code is 4 to 6 digits.")
    if data.get("account_number") and not re.fullmatch(r"\d{6,16}", data["account_number"].replace(" ", "")):
        out.append("The account number is 6 to 16 digits.")
    for key, label, required in DOCUMENTS:
        if required and key not in uploaded_keys:
            out.append(f"Attach the {label.split(' (')[0]}.")
    return out


def submit(pack, values, uploads, declared_name, confirmed, ip=None):
    save(pack, values, uploads)
    data = answers(pack)
    issues = problems(data, set(uploaded(pack)))
    declared = " ".join((declared_name or "").split())[:160]
    if not confirmed or len(declared) < 3:
        issues.append("Tick the declaration and type your full name to submit.")
    if issues:
        db.session.flush()
        return issues                                        # saved, but not submitted
    old = pack.status
    pack.status, pack.submitted_at, pack.submitted_ip, pack.declared_name = "Submitted", now(), ip, declared
    audit.record("starter_pack.submitted", "onboarding_case", pack.case_id, before={"status": old},
                 after={"status": "Submitted", "declared_by": declared, "ip": ip})
    _notify_staff(pack, "submitted", f"{pack.case.employee.full_name} submitted their new starter pack (the Take-On "
                  "form, the Business and Financial Disclosure and the Liberty nomination of beneficiary). As the "
                  "department's HR Business Partner, please review it on the onboarding case: approve it to update "
                  "the employee record, or return it with a comment.")
    return []


# ------------------------------------------------------------------ the HR Business Partner reviews it

def can_review(user, pack):
    """HR Admin or the department's HR Business Partner (16 Nov 2026, at the user's request: like the background
    checks, either of them approves)."""
    from app.services import onboarding
    return (user.has_role(HR_ADMIN) or onboarding.is_case_hrbp(user, pack.case)) and pack.case.status != "Cancelled"


def to_review(user):
    """Submitted packs this user (the department's HR BP) should review, oldest first."""
    packs = NewStarterPack.query.filter_by(status="Submitted").order_by(NewStarterPack.submitted_at).all()
    return [p for p in packs if can_review(user, p)]


def approve(pack, user):
    if not can_review(user, pack):
        raise DomainError("Only HR Admin or the department's HR Business Partner can review the new starter pack.")
    if pack.status != "Submitted":
        raise DomainError("Only a submitted pack can be approved.")
    pack.status, pack.reviewed_by_id, pack.reviewed_at, pack.review_comment = "Approved", user.id, now(), None
    pack.token = None                                         # the link is no longer needed
    changes = apply_to_employee(pack, user)
    audit.record("starter_pack.approved", "onboarding_case", pack.case_id, after={"employee_fields": changes},
                 user=user)
    _notify_staff(pack, "approved", f"{user.full_name} approved {pack.case.employee.full_name}'s new starter pack. "
                  "The employee record has been updated from the Take-On form.", hrbp=False)


def return_pack(pack, user, comment, base_url):
    if not can_review(user, pack):
        raise DomainError("Only HR Admin or the department's HR Business Partner can review the new starter pack.")
    if pack.status != "Submitted":
        raise DomainError("Only a submitted pack can be returned.")
    comment = (comment or "").strip()[:1000]
    if not comment:
        raise DomainError("Say what the new starter must correct.")
    pack.status, pack.reviewed_by_id, pack.reviewed_at, pack.review_comment = "Returned", user.id, now(), comment
    audit.record("starter_pack.returned", "onboarding_case", pack.case_id, after={"comment": comment}, user=user)
    emp = pack.case.employee
    context = {"name": emp.full_name, "title": emp.position_title or "", "comment": comment,
               "ref": pack.case.reference}
    subject, body = render("candidate_starter_pack_returned", context)
    from app.services.emails import designed
    try:
        get_adapter("email").send_email(emp.email, subject, body, html=designed(
            "candidate_starter_pack_returned", subject, body, link(pack, base_url), context))
    except IntegrationError as exc:
        raise DomainError(f"The email to {emp.email} couldn't be sent: {exc}") from exc


def apply_to_employee(pack, user):
    """Approved: the Take-On form's answers onto the employee record. Returns the fields changed."""
    data, emp = answers(pack), pack.case.employee
    account = data.get("account_number", "").replace(" ", "")
    new = {"first_name": data.get("first_names"), "last_name": data.get("surname"),
           "id_number": data.get("id_number") if data.get("sa_citizen") == "Yes" else data.get("passport_number"),
           "date_of_birth": _date(data.get("date_of_birth")), "phone": data.get("cell"),
           "gender": data.get("gender"), "race": data.get("race"),
           "disability": "Yes" if data.get("disability") == "Yes" else "No",
           "bank_account": (f"{data.get('bank_name')} · branch {data.get('branch_code')} · {account} "
                            f"({data.get('account_type')})") if account else None}
    changed = []
    for field, value in new.items():
        if value and getattr(emp, field) != value:
            setattr(emp, field, value)
            changed.append(field)
    if changed:
        audit.record("update", "employee", emp.id, after={"fields": changed}, detail="From the new starter pack",
                     user=user)
    return changed


def _notify_staff(pack, outcome, message, hrbp=True):
    from app.services import onboarding
    case = pack.case
    users = users_with_role(HR_ADMIN)
    if hrbp:
        users.append(onboarding.hrbp_for(case))
    notify(users, "starter_pack_update", link=f"/onboarding/cases/{case.id}", outcome=outcome, message=message,
           status=pack.status, name=case.employee.full_name, title=case.employee.position_title or "",
           ref=case.reference)


# ------------------------------------------------------------------ the printable Take-On form

def _shown(field, value):
    """Dates as "01 January 1980"; everything else as typed."""
    if value and field["kind"] == "date" and _date(value):
        return documents.long_date(_date(value))
    return value


def sections_with_answers(pack):
    data = answers(pack)
    return [(title, [(f["label"], _shown(f, data.get(f["key"], ""))) for f in fields])
            for title, _h, fields in SECTIONS]


def takeon_pdf(pack):
    emp = pack.case.employee
    parts = ["# New Hire Take-On Form",
             f"New starter: {emp.full_name}\nEmployee number: {emp.employee_number}\nCase: {pack.case.reference}\n"
             f"Status: {pack.status}"]
    for title, rows in sections_with_answers(pack):
        lines = [f"{label}: {', '.join(value.split(chr(10))) if value else '-'}" for label, value in rows]
        parts.append(f"# {title}\n" + "\n".join(lines))
    docs = uploaded(pack)
    parts.append("# Supporting documentation\n" + "\n".join(
        f"- {label}: {'received' if key in docs else 'not received'}" for key, label, _r in DOCUMENTS))
    if pack.submitted_at:
        parts.append(f"Declared true and correct by {pack.declared_name} on "
                     f"{documents.long_datetime(pack.submitted_at)} (signed electronically).")
    return documents.pdf("New Hire Take-On Form", "\n\n".join(parts), ref=pack.case.reference)
