"""Careers site and ATS logic, carried over from the original portal (app.py)."""
import os
import secrets

from flask import flash

from app.extensions import db
from app.models import Application, Candidate, Job
from app.services import ats, files
from app.services.dates import now, today
from app.services.errors import DomainError

CV_EXTENSIONS = {".pdf", ".docx"}


def new_reference():
    return "ICE-" + secrets.token_hex(4).upper()


def open_jobs_query():
    return Job.query.filter(Job.status == "Open",
                            db.or_(Job.closing_date.is_(None), Job.closing_date >= today()))


ELIGIBILITY_QUESTION_COUNT = 5


def _question(text, reason):
    return {"text": text, "reason": reason}


def eligibility_questions(job):
    """The yes/no questions asked before the application form (§15.4): the position's minimum requirements first
    (one per line), then the advert's own minimums, then standard questions, always ELIGIBILITY_QUESTION_COUNT."""
    questions = []
    position = job.requisition.approved_position if job.requisition else None
    if position and position.minimum_requirements:
        for line in position.minimum_requirements.splitlines():
            line = line.strip().lstrip("-•*").strip().rstrip(".")
            if line:
                questions.append(_question(f"Do you have {line}?", f"This role requires {line}."))
    if job.min_education:
        label = ats.EDUCATION_LABELS.get(job.min_education, "the required qualification")
        questions.append(_question(f"Do you have at least a {label} qualification?",
                                   f"This role requires at least a {label} qualification."))
    if job.min_experience:
        years = f"{job.min_experience} year{'s' if job.min_experience != 1 else ''}'"
        questions.append(_question(f"Do you have at least {years} relevant work experience?",
                                   f"This role requires at least {years} relevant work experience."))
    if job.required_skills:
        skills = ", ".join(s.strip() for s in job.required_skills.split(",") if s.strip())
        questions.append(_question(f"Do you have working experience in {skills}?",
                                   f"This role requires working experience in {skills}."))
    place = job.location or "the job's location"
    questions += [
        _question("Do you have the right to work in South Africa?",
                  "This role requires the right to work in South Africa."),
        _question(f"Are you able to work in {place}?", f"This role is based in {place}."),
        _question("Can you provide certified copies of your ID and qualifications if you are shortlisted?",
                  "Shortlisted applicants must provide certified copies of their ID and qualifications."),
        _question("Do you agree to background checks (criminal, credit and qualification) if you are shortlisted?",
                  "Shortlisted applicants must agree to background checks."),
        _question("Can you work the hours this role requires?", "This role requires you to work its set hours."),
    ]
    return questions[:ELIGIBILITY_QUESTION_COUNT]


def eligibility_problems(job, answers):
    """Check the applicant's answers (q0..q4 = "yes"/"no"). Returns (unanswered, reasons): unanswered is True when a
    question was skipped; reasons lists why each "no" makes the applicant ineligible. Nothing is stored."""
    reasons, unanswered = [], False
    for i, question in enumerate(eligibility_questions(job)):
        answer = answers.get(f"q{i}")
        if answer not in ("yes", "no"):
            unanswered = True
        elif answer == "no":
            reasons.append(question["reason"])
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


def rescore_job(job):
    for application in Application.query.filter_by(job_id=job.id).all():
        application.score, application.breakdown = ats.score_candidate(job, application.candidate)
