"""ATS admin: job openings, ranked applicants, talent pool and CV database
(carried over from the original portal's /admin pages)."""
import csv
import io
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import Application, Candidate, Job, PanelMember, ShortlistReview, User
from app.models.recruitment import APPLICATION_STATUSES, MESSAGE_KINDS, RECOMMENDATIONS
from app.models.user import HOD, HR_ROLES
from app.services import ats, audit, careers, files, interviews, shortlisting
from app.services.dates import now
from app.services.errors import DomainError
from app.web import back, paginate

bp = Blueprint("recruitment", __name__, url_prefix="/recruitment")
HR = tuple(HR_ROLES)


@bp.route("/")
@roles_required(*HR)
def dashboard():
    week_ago = now() - timedelta(days=7)
    stats = {
        "open_jobs": careers.open_jobs_query().count(),
        "candidates": Candidate.query.count(),
        "applications": Application.query.filter(Application.job_id.isnot(None)).count(),
        "new_this_week": Candidate.query.filter(Candidate.created_at >= week_ago).count(),
    }
    rows = (db.session.query(Job, func.count(Application.id), func.round(func.avg(Application.score), 1),
                             func.sum(db.case((Application.score >= 75, 1), else_=0)))
            .outerjoin(Application, Application.job_id == Job.id)
            .filter(Job.status == "Open").group_by(Job.id).order_by(Job.created_at.desc()).all())
    jobs = [{"id": j.id, "title": j.title, "department": j.department, "location": j.location,
             "applicants": n, "avg_score": avg, "strong": strong} for j, n, avg, strong in rows]
    jobs, pager = paginate(jobs, 10)
    recent = (Application.query.options(joinedload(Application.candidate), joinedload(Application.job))
              .filter(Application.job_id.isnot(None)).order_by(Application.created_at.desc()).limit(8).all())
    recent = [{"candidate_id": a.candidate_id, "full_name": a.candidate.full_name, "title": a.job.title,
               "created_at": a.created_at, "score": a.score} for a in recent]
    pipeline = dict(db.session.query(Application.status, func.count()).filter(Application.job_id.isnot(None))
                    .group_by(Application.status).all())
    return render_template("admin/dashboard.html", stats=stats, jobs=jobs, recent=recent, pipeline=pipeline,
                           pager=pager)


# ------------------------------------------------------------------- jobs

def job_form_values(f):
    def to_int(v):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0
    closing = f.get("closing_date", "").strip()
    try:
        closing = date.fromisoformat(closing) if closing else None
    except ValueError:
        closing = None
    return {
        "title": f.get("title", "").strip(),
        "department": f.get("department", "").strip(),
        "location": f.get("location", "").strip(),
        "job_type": f.get("job_type", "").strip(),
        "description": f.get("description", "").strip(),
        "required_skills": ", ".join(ats.split_skills(f.get("required_skills"))),
        "preferred_skills": ", ".join(ats.split_skills(f.get("preferred_skills"))),
        "min_experience": to_int(f.get("min_experience")),
        "min_education": to_int(f.get("min_education")),
        "closing_date": closing,
        "status": "Closed" if f.get("status") == "Closed" else "Open",
    }


@bp.route("/jobs")
@roles_required(*HR)
def jobs():
    rows = (db.session.query(Job, func.count(Application.id)).outerjoin(Application, Application.job_id == Job.id)
            .group_by(Job.id).order_by(Job.status.desc(), Job.created_at.desc()).all())
    items = []
    for j, n in rows:
        j.applicants = n
        items.append(j)
    items, pager = paginate(items, 20)
    return render_template("admin/jobs.html", jobs=items, pager=pager)


@bp.route("/jobs/new", methods=["GET", "POST"])
@bp.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@roles_required(*HR)
def job_form(job_id=None):
    """Edit a job imported from the old portal. New openings are adverts raised from approved requisitions."""
    job = db.session.get(Job, job_id) if job_id else None
    if job_id and not job:
        abort(404)
    if job is None:
        flash("Openings are advertised from fully approved requisitions.", "info")
        return redirect(url_for("adverts.index"))
    if job.is_advert:
        return redirect(url_for("adverts.detail", job_id=job.id))
    if request.method == "POST":
        values = job_form_values(request.form)
        if not values["title"] or not values["description"]:
            flash("Title and description are required.", "error")
            return render_template("admin/job_form.html", job=values, job_id=job_id)
        if job:
            before = {k: str(getattr(job, k)) for k in values}
            for k, v in values.items():
                setattr(job, k, v)
            careers.rescore_job(job)
            b, a = audit.changes(before, {k: str(v) for k, v in values.items()})
            audit.record("update", "job", job.id, before=b, after=a)
            flash("Job updated and applicants re-scored.", "success")
        else:
            job = Job(created_at=now(), **values)
            db.session.add(job)
            db.session.flush()
            audit.record("create", "job", job.id, after={"title": job.title})
            flash("Job published. Check the Talent Pool tab for existing CVs that match.", "success")
        db.session.commit()
        return redirect(url_for("recruitment.job_detail", job_id=job.id))
    return render_template("admin/job_form.html", job=job or {}, job_id=job_id)


@bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
@roles_required(*HR)
def job_delete(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    audit.record("delete", "job", job.id, before={"title": job.title})
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted. Candidate CVs remain in the talent pool.", "success")
    return redirect(url_for("recruitment.jobs"))


def ranked_applicants(job_id, args):
    q = (db.session.query(Application, Candidate).join(Candidate, Candidate.id == Application.candidate_id)
         .filter(Application.job_id == job_id))
    min_score = args.get("min_score", type=float, default=0)
    if min_score:
        q = q.filter(Application.score >= min_score)
    if args.get("status"):
        q = q.filter(Application.status == args["status"])
    if args.get("q"):
        like = f"%{args['q']}%"
        q = q.filter(db.or_(Candidate.full_name.ilike(like), Candidate.email.ilike(like),
                            Candidate.cv_text.ilike(like), Candidate.skills.ilike(like)))
    order = {"score": Application.score.desc(), "date": Application.created_at.desc(), "name": Candidate.full_name}
    q = q.order_by(order.get(args.get("sort"), Application.score.desc()))
    out = []
    for a, c in q.all():
        out.append({"id": a.id, "reference": a.reference, "candidate_id": c.id, "score": a.score,
                    "status": a.status, "source": a.source, "created_at": a.created_at,
                    "breakdown": a.breakdown or {}, "full_name": c.full_name, "email": c.email,
                    "phone": c.phone, "location": c.location, "current_title": c.current_title,
                    "years_experience": c.years_experience, "education_level": c.education_level})
    return out


@bp.route("/jobs/<int:job_id>")
@roles_required(*HR)
def job_detail(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    tab = request.args.get("tab", "applicants")
    matches, applicants = [], []
    if tab == "pool":
        # Score every CV in the database that hasn't applied for this job.
        min_score = request.args.get("min_score", type=float, default=50)
        applied = db.session.query(Application.candidate_id).filter(Application.job_id == job_id)
        for c in Candidate.query.filter(Candidate.id.notin_(applied)).all():
            score, breakdown = ats.score_candidate(job, c)
            if score >= min_score:
                matches.append({"c": c, "score": score, "breakdown": breakdown})
        matches.sort(key=lambda m: -m["score"])
        matches, pager = paginate(matches, 25)
    else:
        applicants, pager = paginate(ranked_applicants(job_id, request.args), 25)
    total = Application.query.filter_by(job_id=job_id).count()
    counts = dict(db.session.query(Application.status, func.count()).filter(Application.job_id == job_id)
                  .group_by(Application.status).all())
    return render_template("admin/job_detail.html", job=job, tab=tab, applicants=applicants, matches=matches,
                           total=total, args=request.args, pager=pager, counts=counts,
                           review=shortlisting.latest_review(job),
                           department_manager=shortlisting.department_manager_for(job))


@bp.route("/jobs/<int:job_id>/shortlist/<int:cand_id>", methods=["POST"])
@roles_required(*HR)
def shortlist_from_pool(job_id, cand_id):
    job = db.session.get(Job, job_id) or abort(404)
    cand = db.session.get(Candidate, cand_id) or abort(404)
    careers.upsert_application(cand, job, source="Talent pool", status="Shortlisted")
    audit.record("application.shortlisted", "candidate", cand.id, after={"job_id": job.id})
    db.session.commit()
    flash(f"{cand.full_name} added to this job's shortlist.", "success")
    return back("recruitment.job_detail", job_id=job_id)


# ------------------------------------------------- shortlist review and applicant messages (1 Nov 2026)

@bp.route("/jobs/<int:job_id>/shortlist/send", methods=["POST"])
@roles_required(*HR)
def shortlist_send(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    try:
        review = shortlisting.send_to_department_manager(job, current_user)
        db.session.commit()
        flash(f"Shortlist of {len(review.application_ids)} sent to {review.reviewer.full_name}.", "success")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("recruitment.job_detail", job_id=job.id))


@bp.route("/jobs/<int:job_id>/messages", methods=["GET", "POST"])
@roles_required(*HR)
def job_messages(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    kind = request.values.get("kind", "invitation")
    if kind not in MESSAGE_KINDS:
        kind = "invitation"
    if request.method == "POST":
        details = {k: request.form.get(k, "") for k in ("date", "time", "venue", "note")}
        try:
            sent = shortlisting.send_messages(job, current_user, kind, request.form.getlist("app_ids", type=int),
                                              details)
            db.session.commit()
            flash(f"{MESSAGE_KINDS[kind]} sent to {sent} applicant(s).", "success")
            return redirect(url_for("recruitment.job_detail", job_id=job.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/job_messages.html", job=job, kind=kind, kinds=MESSAGE_KINDS,
                           recipients=shortlisting.recipients(job, kind), form=request.form)


@bp.route("/shortlists")
@roles_required(HOD)
def shortlists():
    return render_template("admin/shortlists.html", reviews=shortlisting.reviews_for(current_user))


@bp.route("/shortlists/<int:review_id>", methods=["GET", "POST"])
@roles_required(HOD, *HR)
def shortlist_review(review_id):
    review = db.session.get(ShortlistReview, review_id) or abort(404)
    if review.reviewer_id != current_user.id and not current_user.is_hr:
        abort(403)
    if request.method == "POST":
        try:
            shortlisting.complete_review(review, current_user, request.form.getlist("app_ids", type=int),
                                         request.form.get("comment", ""))
            db.session.commit()
            flash("Thank you. HR has been told who goes to interview.", "success")
            return redirect(url_for("recruitment.shortlists"))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/shortlist_review.html", review=review,
                           can_review=shortlisting.can_review(current_user, review))


@bp.route("/shortlists/<int:review_id>/cv/<int:app_id>")
@roles_required(HOD, *HR)
def shortlist_cv(review_id, app_id):
    review = db.session.get(ShortlistReview, review_id) or abort(404)
    application = db.session.get(Application, app_id) or abort(404)
    if not (current_user.is_hr or shortlisting.reviewer_can_see(current_user, review, application)):
        abort(403)
    return _serve_cv(application.candidate)


# ------------------------------------------------- interview panel and scorecards (1 Nov 2026)

@bp.route("/jobs/<int:job_id>/panel", methods=["GET", "POST"])
@roles_required(*HR)
def panel(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    panel = interviews.panel_for(job, create=True)
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "add":
                member = interviews.add_member(panel, db.session.get(User, request.form.get("user_id", type=int) or 0),
                                               current_user)
                message = f"{member.user.full_name} added to the panel and notified."
            elif action == "remove":
                member = db.session.get(PanelMember, request.form.get("member_id", type=int) or 0)
                if member is None or member.panel_id != panel.id:
                    abort(404)
                interviews.remove_member(panel, member, current_user)
                message = "Removed from the panel."
            elif action == "criteria":
                interviews.save_criteria(panel, zip(request.form.getlist("c_name"), request.form.getlist("c_weight")))
                message = "Scoring criteria saved."
            elif action == "slots":
                for app in interviews.candidates(job):
                    d, t = request.form.get(f"date_{app.id}", ""), request.form.get(f"time_{app.id}", "")
                    venue = request.form.get(f"venue_{app.id}", "")
                    if not (d or t or venue) and app.slot is None:
                        continue
                    try:
                        starts = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
                    except ValueError:
                        starts = None
                    interviews.set_slot(app, starts, venue)
                message = "Interview slots saved."
            elif action == "invite":
                members, invited = interviews.send_invitations(job, current_user)
                message = (f"Invitations sent to the {members} panel member(s)"
                           f"{f' and {invited} candidate(s)' if invited else ''}.")
            else:
                abort(400)
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("recruitment.panel", job_id=job.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    db.session.commit()                                     # a new panel is kept
    return render_template("admin/panel.html", job=job, panel=panel, apps=interviews.candidates(job),
                           eligible=interviews.eligible_members(panel), results=interviews.ranking(job),
                           form=request.form)


@bp.route("/interviews")
@roles_required()
def interviews_to_score():
    return render_template("admin/interviews.html", rows=interviews.to_score(current_user),
                           waiting=interviews.waiting_panels(current_user))


def _scorable(app_id):
    application = db.session.get(Application, app_id) or abort(404)
    if not (current_user.is_hr or interviews.membership(current_user, application.job)):
        abort(403)
    return application


@bp.route("/interviews/<int:app_id>", methods=["GET", "POST"])
@roles_required()
def scorecard(app_id):
    application = _scorable(app_id)
    panel = interviews.panel_for(application.job)
    if request.method == "POST":
        try:
            scores = {c["name"]: request.form.get(f"score_{i}") for i, c in enumerate(panel.criteria)}
            interviews.submit_scorecard(application, current_user, scores, request.form.get("comment", ""),
                                        request.form.get("recommendation"))
            db.session.commit()
            flash(f"Your scores for {application.candidate.full_name} are in.", "success")
            return redirect(url_for("recruitment.scorecard", app_id=application.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/scorecard.html", app=application, panel=panel,
                           mine=interviews.my_scorecard(current_user, application),
                           can_score=interviews.can_score(current_user, application),
                           show_all=interviews.can_see_scores(current_user, application),
                           result=interviews.result(application, panel), recommendations=RECOMMENDATIONS,
                           form=request.form)


@bp.route("/interviews/<int:app_id>/cv")
@roles_required()
def interview_cv(app_id):
    return _serve_cv(_scorable(app_id).candidate)


@bp.route("/interviews/<int:app_id>/invite.ics")
@roles_required()
def interview_ics(app_id):
    application = _scorable(app_id)
    if not (application.slot and application.slot.ics):
        abort(404)
    return Response(application.slot.ics, mimetype="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="interview-{application.reference}.ics"'})


@bp.route("/jobs/<int:job_id>/export.csv")
@roles_required(*HR)
def job_export(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rank", "Reference", "Name", "Email", "Phone", "Location", "Score %", "Status",
                "Missing required skills", "Applied"])
    for i, a in enumerate(ranked_applicants(job_id, request.args), 1):
        missing = a["breakdown"].get("components", {}).get("required", {}).get("missing", [])
        w.writerow([i, a["reference"], a["full_name"], a["email"], a["phone"], a["location"],
                    a["score"], a["status"], "; ".join(missing), a["created_at"].date().isoformat()])
    audit.record("export", "job", job.id, detail="Applicants CSV")
    db.session.commit()
    name = secure_filename(job.title) or "job"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}_applicants.csv"})


# ------------------------------------------------------------- candidates

@bp.route("/candidates")
@roles_required(*HR)
def candidates():
    args = request.args
    q = Candidate.query
    if args.get("q"):
        for term in args["q"].split():
            like = f"%{term}%"
            q = q.filter(db.or_(Candidate.full_name.ilike(like), Candidate.email.ilike(like),
                                Candidate.skills.ilike(like), Candidate.cv_text.ilike(like),
                                Candidate.current_title.ilike(like)))
    if args.get("location"):
        q = q.filter(Candidate.location.ilike(f"%{args['location']}%"))
    min_exp = args.get("min_exp", type=int, default=0)
    if min_exp:
        q = q.filter(func.coalesce(Candidate.years_experience, 0) >= min_exp)
    q = q.order_by(Candidate.updated_at.desc())

    job_id = args.get("job_id", type=int)
    job = db.session.get(Job, job_id) if job_id else None
    min_score = args.get("min_score", type=float, default=0)
    if job:
        results = []
        for c in q.all():
            score, breakdown = ats.score_candidate(job, c)
            if score >= min_score:
                results.append({"c": c, "score": score, "breakdown": breakdown})
        results.sort(key=lambda r: -r["score"])
        results, pager = paginate(results, 50)
    else:
        rows, pager = paginate(q, 50)
        results = [{"c": c, "score": None, "breakdown": None} for c in rows]
    jobs = Job.query.with_entities(Job.id, Job.title, Job.status).order_by(Job.status.desc(), Job.title).all()
    return render_template("admin/candidates.html", results=results, jobs=jobs, job=job, args=args, pager=pager)


@bp.route("/candidates/<int:cand_id>")
@roles_required(*HR)
def candidate(cand_id):
    cand = db.session.get(Candidate, cand_id) or abort(404)
    apps = (Application.query.options(joinedload(Application.job)).filter_by(candidate_id=cand_id)
            .order_by(Application.created_at.desc()).all())
    apps = [{"id": a.id, "job_id": a.job_id, "title": a.job.title if a.job else None, "status": a.status,
             "score": a.score, "source": a.source, "created_at": a.created_at, "notes": a.notes,
             "cover_note": a.cover_note, "reference": a.reference, "breakdown": a.breakdown or {}} for a in apps]
    audit.record("data.view", "candidate", cand.id)
    db.session.commit()
    return render_template("admin/candidate.html", cand=cand, apps=apps)


@bp.route("/candidates/<int:cand_id>/cv")
@roles_required(*HR)
def candidate_cv(cand_id):
    return _serve_cv(db.session.get(Candidate, cand_id) or abort(404))


def _serve_cv(cand):
    if not cand.cv_file:
        abort(404)
    stored = cand.cv_file
    disposition = "inline" if stored.content_type == "application/pdf" and not request.args.get("download") \
        else "attachment"
    audit.record("file.download", "candidate", cand.id, after={"file_id": stored.id})
    db.session.commit()
    return Response(files.read(stored), mimetype=stored.content_type,
                    headers={"Content-Disposition": f'{disposition}; filename="{stored.original_name}"',
                             "X-Content-Type-Options": "nosniff"})


@bp.route("/candidates/<int:cand_id>/delete", methods=["POST"])
@roles_required(*HR)
def candidate_delete(cand_id):
    cand = db.session.get(Candidate, cand_id) or abort(404)
    audit.record("delete", "candidate", cand.id, before={"name": cand.full_name}, detail="POPIA erasure")
    stored = cand.cv_file
    db.session.delete(cand)
    if stored:
        files.delete(stored)
    db.session.commit()
    flash("Candidate and their CV permanently deleted.", "success")
    return redirect(url_for("recruitment.candidates"))


@bp.route("/applications/<int:app_id>/update", methods=["POST"])
@roles_required(*HR)
def application_update(app_id):
    application = db.session.get(Application, app_id) or abort(404)
    status = request.form.get("status")
    if status and status not in APPLICATION_STATUSES:
        abort(400)
    before = {"status": application.status, "notes": application.notes}
    if status:
        application.status = status
    if request.form.get("notes") is not None:
        application.notes = request.form.get("notes")
    b, a = audit.changes(before, {"status": application.status, "notes": application.notes})
    audit.record("update", "application", application.id, before=b, after=a)
    db.session.commit()
    flash("Application updated.", "success")
    return back("recruitment.dashboard")


@bp.route("/applications/bulk", methods=["POST"])
@roles_required(*HR)
def application_bulk():
    ids = request.form.getlist("app_ids", type=int)
    status = request.form.get("status")
    if ids and status in APPLICATION_STATUSES:
        for application in Application.query.filter(Application.id.in_(ids)).all():
            audit.record("status_change", "application", application.id, before={"status": application.status},
                         after={"status": status})
            application.status = status
        db.session.commit()
        flash(f"{len(ids)} application(s) moved to {status}.", "success")
    else:
        flash("Select at least one applicant and a status.", "error")
    return back("recruitment.dashboard")
