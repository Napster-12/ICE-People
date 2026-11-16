"""Careers site and ATS logic, carried over from the original portal (app.py)."""
import logging
import os
import re
import secrets

from flask import flash

from app.extensions import db
from app.models import Application, Candidate, Job
from app.services import ats, files
from app.services.dates import now, today
from app.services.errors import DomainError

log = logging.getLogger(__name__)
CV_EXTENSIONS = {".pdf", ".docx"}

# ------------------------------------------------------------------ the applicant's profile (16 Nov 2026)
# Asked on the apply and talent-pool forms, at the user's request, so a successful candidate's employee record, offer
# letter and Take-On form start filled in. The EE fields are voluntary ("Prefer not to say"), are never used in the
# ATS score and aren't shown to shortlisting or the panel.
TITLES = ["Mr", "Ms", "Mrs", "Miss", "Dr", "Prof"]
NOTICE_PERIODS = ["Immediately", "1 week", "2 weeks", "1 month", "2 months", "3 months", "Other"]
LICENCES = ["None", "Code A (motorcycle)", "Code B (light vehicle)", "Code C1", "Code C", "Code EB", "Code EC1",
            "Code EC"]
PREFER_NOT = "Prefer not to say"
GENDERS = ["Male", "Female", PREFER_NOT]
RACES = ["African", "Coloured", "Indian", "White", "Other", PREFER_NOT]
DISABILITY = ["No", "Yes", PREFER_NOT]
DOC_TYPES = {".pdf", ".jpg", ".jpeg", ".png"}


def provinces():
    from app.services.places import PROVINCE_PLACES
    return list(PROVINCE_PLACES)


def required_documents():
    """Documents every job applicant attaches (HR Admin edits the list, one per line)."""
    from app.services import settings
    return [line.strip() for line in settings.get("application_documents").splitlines() if line.strip()]


def optional_documents():
    from app.services import settings
    return [line.strip() for line in settings.get("application_optional_documents").splitlines() if line.strip()]


def _money(raw, label, errors):
    from decimal import Decimal, InvalidOperation
    raw = (raw or "").replace(" ", "").replace(",", "").replace("R", "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw).quantize(Decimal("0.01"))
        if value < 0 or value > 100_000_000:
            raise InvalidOperation
        return value
    except InvalidOperation:
        errors.append(f"{label} must be an amount, e.g. 25000.")
        return None


MAX_SKILLS = 30


def clean_skills(values):
    """The applicant's skills, one per line (16 Nov 2026, at the user's request: a line each reads better for the ATS
    than one comma list). A row with commas or semicolons is split too. Deduplicated, at most MAX_SKILLS."""
    out, seen = [], set()
    for value in values or []:
        for part in re.split(r"[,;\n]", value or ""):
            skill = " ".join(part.split())[:60]
            if skill and skill.lower() not in seen:
                seen.add(skill.lower())
                out.append(skill)
    return "\n".join(out[:MAX_SKILLS])


def skill_list(value):
    """Stored skills (one per line, or the older comma list) → a list for display."""
    return [s.strip() for s in re.split(r"[,;\n]", value or "") if s.strip()]


def parse_profile(form):
    """The profile fields → (clean values, errors)."""
    from datetime import date
    from app.services.validators import sa_id_birth_date, validate_sa_id
    errors, out = [], {}

    def text(key, limit=160):
        return " ".join((form.get(key) or "").split())[:limit]

    def choice(key, options, label, required=True):
        value = form.get(key) or ""
        if value and value not in options:
            errors.append(f"Choose an option for {label}.")
            return None
        if required and not value:
            errors.append(f"Please choose your {label}.")
        return value or None

    out["title"] = choice("title", TITLES, "title")
    out["first_names"], out["surname"] = text("first_names", 100), text("surname", 80)
    if not out["first_names"]:
        errors.append("Please enter your first names.")
    if not out["surname"]:
        errors.append("Please enter your surname.")
    out["sa_citizen"] = choice("sa_citizen", ["Yes", "No"], "citizenship")
    number = "".join((form.get("id_number") or "").split()).upper()[:20]
    out["id_number"], out["date_of_birth"], out["nationality"], out["work_permit_expiry"] = number or None, None, None, None
    if out["sa_citizen"] == "Yes":
        out["nationality"] = "South African"
        if not number:
            errors.append("Please enter your SA ID number.")
        else:
            problems = validate_sa_id(number)
            errors += problems
            if not problems:
                out["date_of_birth"] = sa_id_birth_date(number)
    elif out["sa_citizen"] == "No":
        out["nationality"] = text("nationality", 80) or None
        if not out["nationality"]:
            errors.append("Please enter your nationality.")
        if not (number and 6 <= len(number) <= 20 and number.isalnum()):
            errors.append("Please enter your passport number.")
        for key, label in (("date_of_birth", "date of birth"), ("work_permit_expiry", "work permit expiry date")):
            raw = form.get(key) or ""
            try:
                out[key] = date.fromisoformat(raw) if raw else None
            except ValueError:
                errors.append(f"Enter your {label} as a date.")
        if out["date_of_birth"] is None:
            errors.append("Please enter your date of birth.")

    phone = text("phone", 40)
    if len("".join(c for c in phone if c.isdigit())) < 9:
        errors.append("Please enter your cellphone number.")
    out["phone"], out["alt_phone"] = phone, text("alt_phone", 40) or None
    out["street"], out["suburb"] = text("street"), text("suburb", 120) or None
    out["city"], out["postal_code"] = text("city", 120), text("postal_code", 10)
    picked = out["city"].rsplit(", ", 1)                     # a suggestion: "Durban, KwaZulu-Natal"
    if len(picked) == 2 and picked[1] in provinces():
        out["city"] = picked[0]
        if not form.get("province"):
            form = {**form.to_dict(), "province": picked[1]} if hasattr(form, "to_dict") else {**form,
                                                                                               "province": picked[1]}
    out["province"] = choice("province", provinces(), "province")
    for key, label in (("street", "street address"), ("city", "city or town"), ("postal_code", "postal code")):
        if not out[key]:
            errors.append(f"Please enter your {label}.")
    if out["postal_code"] and not (out["postal_code"].isdigit() and len(out["postal_code"]) == 4):
        errors.append("The postal code has 4 digits.")

    out["current_employer"] = text("current_employer") or None
    out["notice_period"] = choice("notice_period", NOTICE_PERIODS, "notice period")
    out["current_salary"] = _money(form.get("current_salary"), "Current salary", errors)
    out["expected_salary"] = _money(form.get("expected_salary"), "Expected salary", errors)
    out["drivers_licence"] = choice("drivers_licence", LICENCES, "driver's licence")
    out["own_transport"] = choice("own_transport", ["Yes", "No"], "own transport", required=False)
    out["languages"] = text("languages", 255) or None
    out["gender"] = choice("gender", GENDERS, "gender")
    out["race"] = choice("race", RACES, "race")
    out["disability"] = choice("disability", DISABILITY, "disability status")
    return out, errors


def check_documents(uploads, documents_required=True):
    """uploads: {document name: FileStorage}. Returns [(name, filename, bytes)] or the errors, checked before anything
    is stored. Optional documents are taken when attached."""
    from flask import current_app
    limit = current_app.config["MAX_UPLOAD_BYTES"]
    ready, errors, missing = [], [], []
    required = required_documents() if documents_required else []
    for name in required + optional_documents() + ([] if documents_required else required_documents()):
        upload = (uploads or {}).get(name)
        if upload is None or not upload.filename:
            if name in required:
                missing.append(name)
            continue
        ext = os.path.splitext(upload.filename)[1].lower()
        data = upload.read()
        if ext not in DOC_TYPES:
            errors.append(f"{name} must be a PDF, JPG or PNG file.")
        elif not data:
            errors.append(f"The file for {name} is empty.")
        elif len(data) > limit:
            errors.append(f"{name} is larger than {limit // (1024 * 1024)} MB.")
        else:
            ready.append((name, upload.filename, data))
    if missing:
        errors.insert(0, "Please attach: " + ", ".join(missing) + ".")
    return ready, errors


def store_documents(candidate, ready):
    """Keep the documents on the candidate (one current file per document name; a new one replaces the old)."""
    current = dict(candidate.documents or {})
    for name, filename, data in ready:
        stored = files.store_bytes(data, f"{name} - {filename}"[:255], "candidate_document", candidate.id,
                                   check=False)
        old = current.get(name)
        current[name] = stored.id
        if old:
            from app.models import StoredFile
            previous = db.session.get(StoredFile, old)
            if previous is not None:
                files.delete(previous)
    candidate.documents = current


def candidate_documents(candidate):
    """[(document name, StoredFile)] in the order applicants see them."""
    from app.models import StoredFile
    order = required_documents() + optional_documents()
    items = []
    for name, file_id in (candidate.documents or {}).items():
        stored = db.session.get(StoredFile, file_id)
        if stored is not None:
            items.append((name, stored))
    return sorted(items, key=lambda item: order.index(item[0]) if item[0] in order else len(order))


def address_lines(candidate):
    """For the offer letter: street, suburb, city, postal code, one per line."""
    lines = [candidate.street, candidate.suburb, candidate.city, candidate.postal_code]
    return "\n".join(line for line in lines if line) or None


def new_reference():
    return "ICE-" + secrets.token_hex(4).upper()


def open_jobs_query():
    return Job.query.filter(Job.status == "Open",
                            db.or_(Job.closing_date.is_(None), Job.closing_date >= today()))


def eligibility_questions(job):
    """The yes/no questions asked before the application form (§15.4). The Talent Acquisition Specialist types them
    on each advert (6 Nov 2026, at the user's request): [{"text", "answer"}], where answer ("yes" or "no") qualifies.
    None typed (old imported jobs): no check."""
    return [q for q in (job.eligibility_questions or []) if (q.get("text") or "").strip()]


def eligibility_problems(job, answers):
    """Check the applicant's answers (q0, q1, ... = "yes"/"no"). Returns (unanswered, reasons): unanswered is True
    when a question was skipped; reasons lists each question answered the wrong way. Nothing is stored."""
    reasons, unanswered = [], False
    for i, question in enumerate(eligibility_questions(job)):
        answer = answers.get(f"q{i}")
        if answer not in ("yes", "no"):
            unanswered = True
        elif answer != question.get("answer", "yes"):
            reasons.append(f"{question['text']} This role needs the answer "
                           f"\u201c{question.get('answer', 'yes').capitalize()}\u201d.")
    return unanswered, reasons


def save_candidate_from_form(form, upload, uploads=None, documents_required=True):
    """Validate the application form, create/update the candidate (CV and documents stored as files)
    and return them, or None after flashing errors. documents_required: False on the talent-pool form."""
    profile, errors = parse_profile(form)
    full_name = " ".join(p for p in (profile["first_names"], profile["surname"]) if p)
    email = form.get("email", "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        errors.append("Please enter a valid email address.")
    if not form.get("consent"):
        errors.append("Please consent to us storing your information (POPIA).")

    ext = os.path.splitext(upload.filename)[1].lower() if upload and upload.filename else ""
    if not upload or not upload.filename:
        errors.append("Please upload your CV.")
    elif ext not in CV_EXTENSIONS:
        errors.append("CV must be a PDF or Word (.docx) file.")

    years = form.get("years_experience", "").strip()
    try:
        years = max(0, min(50, int(years))) if years else None
    except ValueError:
        errors.append("Years of experience must be a number.")
        years = None

    ready, doc_errors = check_documents(uploads, documents_required)
    errors += doc_errors
    if errors:
        for e in errors:
            flash(e, "error")
        return None

    data = upload.read()
    try:
        stored = files.store_bytes(data, upload.filename, "candidate", allowed=CV_EXTENSIONS)
    except DomainError as exc:
        flash(str(exc), "error")
        return None
    try:
        edu = int(form.get("education_level") or 0)
    except ValueError:
        edu = 0
    candidate = Candidate.query.filter_by(email=email).first()
    old_file = None
    if candidate is None:
        candidate = Candidate(email=email)
        db.session.add(candidate)
    else:
        old_file = candidate.cv_file
    candidate.full_name = full_name
    for key, value in profile.items():
        setattr(candidate, key, value)
    candidate.location = ", ".join(p for p in (profile["city"], profile["province"]) if p)
    candidate.current_title = form.get("current_title", "").strip()
    candidate.years_experience = years
    candidate.education_level = edu
    candidate.skills = clean_skills(form.getlist("skills") if hasattr(form, "getlist") else [form.get("skills", "")])
    candidate.cv_file = stored
    candidate.cv_text = ats.extract_text(stored.original_name, data)
    candidate.consent = True
    candidate.consent_at = now()
    db.session.flush()
    stored.entity_id = candidate.id
    if old_file is not None:
        files.delete(old_file)
    store_documents(candidate, ready)
    return candidate


def upsert_application(candidate, job, cover_note="", source="Applied", status=None):
    """Create (or refresh) the candidate's application for a job / the talent pool."""
    if job is not None:
        score, breakdown = ats.score_candidate(job, candidate)
        existing = Application.query.filter_by(candidate_id=candidate.id, job_id=job.id).first()
    else:
        score, breakdown = 0, {}
        existing = Application.query.filter_by(candidate_id=candidate.id, job_id=None).first()
    if existing:
        existing.score, existing.breakdown = score, breakdown
        if cover_note:
            existing.cover_note = cover_note
        return existing.reference
    ref = new_reference()
    db.session.add(Application(reference=ref, candidate_id=candidate.id, job_id=job.id if job else None,
                               cover_note=cover_note, score=score, breakdown=breakdown,
                               status=status or "New", source=source))
    return ref


def send_application_received(application):
    """Email the applicant that their application arrived (spec IN-010 acknowledgement; 8 Nov 2026, at the user's
    request). A failed email never loses the application: it's logged in the Integration Log."""
    from app.integrations import IntegrationError, get_adapter
    from app.services.dates import format_datetime
    from app.services.emails import designed
    from app.services.notifications import render
    candidate = application.candidate
    if not candidate or not candidate.email:
        return False
    key = "candidate_application_received"
    title = application.job.title if application.job else ""
    subject, body = render(key, {"name": candidate.full_name, "title": title, "ref": application.reference,
                                 "date": format_datetime(application.created_at or now())})
    try:
        get_adapter("email").send_email(candidate.email, subject, body, html=designed(key, subject, body))
    except IntegrationError as exc:
        log.error("Application received email to %s failed: %s", candidate.email, exc)
        return False
    return True


def rescore_job(job):
    for application in Application.query.filter_by(job_id=job.id).all():
        application.score, application.breakdown = ats.score_candidate(job, application.candidate)


def set_application_documents(required_text, optional_text, user):
    """HR Admin: the documents asked for when applying (16 Nov 2026). A name can't be both required and optional."""
    from app.services import audit, settings

    def names(text):
        out = []
        for line in (text or "").splitlines():
            name = " ".join(line.split())[:100]
            if name and name.lower() not in {n.lower() for n in out}:
                out.append(name)
        return out
    required = names(required_text)
    optional = [n for n in names(optional_text) if n.lower() not in {r.lower() for r in required}]
    if len(required) + len(optional) > 15:
        raise DomainError("List 15 documents at most.")
    for key, value in (("application_documents", "\n".join(required)),
                       ("application_optional_documents", "\n".join(optional))):
        if value != settings.get(key):
            audit.record("config.setting", "setting", key, before={"value": settings.get(key)}, after={"value": value},
                         user=user)
            settings.set_value(key, value)
    return required, optional
