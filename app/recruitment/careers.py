"""Public careers site (carried over from the original portal). No sign-in needed."""
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

from app.extensions import db
from app.models import Application, Candidate, Job
from app.services import audit, careers
from app.web import paginate

bp = Blueprint("careers", __name__)


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    dept = request.args.get("department", "").strip()
    job_type = request.args.get("job_type", "").strip()
    query = careers.open_jobs_query()
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Job.title.ilike(like), Job.description.ilike(like), Job.required_skills.ilike(like)))
    if location:
        query = query.filter(Job.location.ilike(f"%{location}%"))
    if dept:
        query = query.filter(Job.department == dept)
    if job_type:
        query = query.filter(Job.job_type == job_type)
    jobs, pager = paginate(query.order_by(Job.created_at.desc()), 12)

    # Filter sidebar counts are taken over all open jobs.
    def counts(column):
        sub = careers.open_jobs_query().subquery()
        col = getattr(sub.c, column)
        return db.session.query(col, func.count()).filter(col.isnot(None), col != "") \
            .group_by(col).order_by(col).all()

    total_open = careers.open_jobs_query().count()
    return render_template("public/index.html", jobs=jobs, q=q, location=location, dept=dept,
                           job_type=job_type, total_open=total_open, departments=counts("department"),
                           types=counts("job_type"), locations=counts("location"),
                           filtered=any([q, location, dept, job_type]), pager=pager)


def _open_job_or_redirect(job_id):
    job = careers.open_jobs_query().filter(Job.id == job_id).first()
    if not job:
        flash("That position is no longer open. You can still submit your CV to our talent pool.", "info")
    return job


@bp.route("/jobs/<int:job_id>", methods=["GET", "POST"])
def job_detail(job_id):
    """Step 1 of 2: the eligibility check. Answers are only checked, never stored."""
    job = _open_job_or_redirect(job_id)
    if not job:
        return redirect(url_for("careers.index"))
    questions = careers.eligibility_questions(job)
    if request.method == "POST":
        unanswered, reasons = careers.eligibility_problems(job, request.form)
        if unanswered:
            flash("Please answer every question with Yes or No.", "error")
        elif reasons:
            session["ineligible"] = {"title": job.title, "reasons": reasons}
            return redirect(url_for("careers.talent_pool"))
        else:
            session["eligible_jobs"] = sorted(set(session.get("eligible_jobs", [])) | {job.id})
            return redirect(url_for("careers.apply", job_id=job.id))
    return render_template("public/job.html", job=job, questions=questions, answers=request.form)


@bp.route("/jobs/<int:job_id>/apply", methods=["GET", "POST"])
def apply(job_id):
    """Step 2 of 2: the application form, only after the eligibility check is passed."""
    job = _open_job_or_redirect(job_id)
    if not job:
        return redirect(url_for("careers.index"))
    if job.id not in session.get("eligible_jobs", []):
        flash("Please answer the eligibility questions first.", "info")
        return redirect(url_for("careers.job_detail", job_id=job.id, _anchor="check"))
    if request.method == "POST":
        candidate = careers.save_candidate_from_form(request.form, request.files.get("cv"))
        if candidate:
            ref = careers.upsert_application(candidate, job, request.form.get("cover_note", "").strip())
            # Every CV also lives in the talent pool for future openings.
            careers.upsert_application(candidate, None, source="Talent pool")
            audit.record("application.submitted", "candidate", candidate.id, after={"job_id": job.id, "ref": ref},
                         detail="POPIA consent given")
            db.session.commit()
            session["eligible_jobs"] = [j for j in session.get("eligible_jobs", []) if j != job.id]
            return redirect(url_for("careers.application_done", ref=ref))
        db.session.rollback()
    return render_template("public/apply.html", job=job, form=request.form)


@bp.route("/talent-pool", methods=["GET", "POST"])
def talent_pool():
    if request.method == "POST":
        candidate = careers.save_candidate_from_form(request.form, request.files.get("cv"))
        if candidate:
            ref = careers.upsert_application(candidate, None, request.form.get("cover_note", "").strip(),
                                             source="Talent pool")
            audit.record("application.submitted", "candidate", candidate.id, after={"ref": ref},
                         detail="Talent pool; POPIA consent given")
            db.session.commit()
            return redirect(url_for("careers.application_done", ref=ref))
        db.session.rollback()
    # Shown once when the applicant was sent here from a failed eligibility check.
    ineligible = session.pop("ineligible", None) if request.method == "GET" else None
    return render_template("public/talent_pool.html", form=request.form, ineligible=ineligible)


@bp.route("/thank-you/<ref>")
def application_done(ref):
    application = Application.query.filter_by(reference=ref).first()
    if not application:
        abort(404)
    app_row = {"reference": application.reference, "title": application.job.title if application.job else None}
    return render_template("public/thanks.html", app_row=app_row)


@bp.route("/status", methods=["GET", "POST"])
def check_status():
    result = None
    if request.method == "POST":
        ref = request.form.get("reference", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        application = (Application.query.join(Candidate)
                       .filter(Application.reference == ref, Candidate.email == email).first())
        if application:
            result = {"reference": application.reference, "status": application.status,
                      "created_at": application.created_at, "updated_at": application.updated_at,
                      "title": application.job.title if application.job else None}
        else:
            flash("We couldn't find an application with that reference and email.", "error")
    return render_template("public/status.html", result=result)
