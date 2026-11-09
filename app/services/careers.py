"""Careers site and ATS logic, carried over from the original portal (app.py)."""
import logging
import os
import secrets

from flask import flash

from app.extensions import db
from app.models import Application, Candidate, Job
from app.services import ats, files
from app.services.dates import now, today
from app.services.errors import DomainError

log = logging.getLogger(__name__)
CV_EXTENSIONS = {".pdf", ".docx"}


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


def save_candidate_from_form(form, upload):
    """Validate the application form, create/update the candidate (CV stored as a file)
    and return them, or None after flashing errors."""
    errors = []
    full_name = form.get("full_name", "").strip()
    email = form.get("email", "").strip().lower()
    if not full_name:
        errors.append("Please enter your full name.")
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
    candidate.phone = form.get("phone", "").strip()
    candidate.location = form.get("location", "").strip()
    candidate.current_title = form.get("current_title", "").strip()
    candidate.years_experience = years
    candidate.education_level = edu
    candidate.skills = form.get("skills", "").strip()
    candidate.cv_file = stored
    candidate.cv_text = ats.extract_text(stored.original_name, data)
    candidate.consent = True
    candidate.consent_at = now()
    db.session.flush()
    stored.entity_id = candidate.id
    if old_file is not None:
        files.delete(old_file)
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
