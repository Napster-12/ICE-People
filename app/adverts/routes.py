"""Job adverts and the JD library (REQ-JA-001–008, spec §4.4)."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import AuditLog, Job, JobDescriptionTemplate, JobFamily, Requisition
from app.models.recruitment import ADVERT_STATUSES, JOB_TYPES
from app.models.user import HR_ROLES
from app.services import adverts, ats, workflow
from app.services.dates import today
from app.services.errors import DomainError
from app.web import paginate

bp = Blueprint("adverts", __name__, url_prefix="/adverts")
HR = tuple(HR_ROLES)


def _advert(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    if not job.is_advert:
        abort(404)
    return job


def _int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@bp.route("/")
@roles_required(*HR)
def index():
    status = request.args.get("status", "")
    q = Job.query.options(joinedload(Job.requisition)).filter(Job.reference.isnot(None))
    if status:
        q = q.filter(Job.status == status)
    rows, pager = paginate(q.order_by(Job.created_at.desc()), 20)
    ready = adverts.ready_query().order_by(Requisition.approved_at).all()
    return render_template("adverts/index.html", rows=rows, pager=pager, ready=ready, statuses=ADVERT_STATUSES,
                           status=status)


@bp.route("/new/<int:req_id>", methods=["GET", "POST"])
@roles_required(*HR)
def new(req_id):
    req = db.session.get(Requisition, req_id) or abort(404)
    existing = adverts.advert_for(req)
    if existing is not None:
        return redirect(url_for("adverts.detail", job_id=existing.id))
    templates = JobDescriptionTemplate.query.filter_by(active=True).order_by(JobDescriptionTemplate.title).all()
    if request.method == "POST":
        template_id = request.form.get("template_id", type=int) or 0
        template = db.session.get(JobDescriptionTemplate, template_id) if template_id else None
        try:
            job = adverts.draft_from_requisition(req, current_user, template=template, use_library=bool(template_id))
            db.session.commit()
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("requisitions.detail", req_id=req.id))
        flash(f"Advert {job.reference} drafted. Check the content, then send it to the HR Manager for approval.",
              "success")
        return redirect(url_for("adverts.edit", job_id=job.id))
    if req.status != "Approved":
        flash("Only fully approved requisitions can be advertised.", "error")
        return redirect(url_for("requisitions.detail", req_id=req.id))
    match = adverts.match_template(req.approved_position) if req.approved_position else None
    return render_template("adverts/new.html", req=req, templates=templates, match=match)


def _values(f):
    return {
        "title": f.get("title", "").strip(),
        "location": f.get("location", "").strip(),
        "job_type": f.get("job_type", "").strip(),
        "description": f.get("description", "").strip(),
        "required_skills": ", ".join(ats.split_skills(f.get("required_skills"))),
        "preferred_skills": ", ".join(ats.split_skills(f.get("preferred_skills"))),
        "min_experience": _int(f.get("min_experience"), None) if f.get("min_experience", "").strip() else None,
        "min_education": _int(f.get("min_education")),
        "closing_date": _date(f.get("closing_date", "").strip()),
        "ee_statement": f.get("ee_statement", "").strip(),
        "channels": [c for c in adverts.CHANNELS if c in f.getlist("channels")],
    }


@bp.route("/<int:job_id>/edit", methods=["GET", "POST"])
@roles_required(*HR)
def edit(job_id):
    job = _advert(job_id)
    if job.status not in adverts.EDITABLE:
        flash("Only draft or returned adverts can be edited.", "error")
        return redirect(url_for("adverts.detail", job_id=job.id))
    if request.method == "POST":
        # Edits are kept even when the advert isn't ready to send for approval yet.
        adverts.save(job, _values(request.form), current_user)
        db.session.commit()
        if request.form.get("action") != "submit":
            flash("Advert saved.", "success")
            return redirect(url_for("adverts.detail", job_id=job.id))
        try:
            adverts.submit(job, current_user)
            db.session.commit()
            flash(f"{job.reference} sent to the HR Manager for approval.", "success")
            return redirect(url_for("adverts.detail", job_id=job.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("adverts/form.html", job=job, job_types=JOB_TYPES, channels=adverts.CHANNELS,
                           education_levels=ats.EDUCATION_LEVELS, problems=adverts.problems(job))


@bp.route("/<int:job_id>")
@roles_required(*HR)
def detail(job_id):
    job = _advert(job_id)
    instances = workflow.history("advert", job.id)
    current = instances[0] if instances else None
    my_step = None
    if current and current.status == "Pending":
        step = current.current_step
        if step and workflow.can_act(step, current_user):
            my_step = step
    timeline = (AuditLog.query.filter_by(entity="advert", entity_id=str(job.id))
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).all())
    return render_template("adverts/detail.html", job=job, instances=instances, current=current, my_step=my_step,
                           timeline=timeline, stats=adverts.stats(job), careers_site=adverts.CAREERS_SITE,
                           education=adverts.education_label(job.min_education), problems=adverts.problems(job))


def _act(job_id, fn, done):
    job = _advert(job_id)
    try:
        fn(job)
        db.session.commit()
        flash(done(job), "success")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return job


@bp.route("/<int:job_id>/submit", methods=["POST"])
@roles_required(*HR)
def submit(job_id):
    _act(job_id, lambda j: adverts.submit(j, current_user),
         lambda j: f"{j.reference} sent to the HR Manager for approval.")
    return redirect(url_for("adverts.detail", job_id=job_id))


@bp.route("/<int:job_id>/close", methods=["POST"])
@roles_required(*HR)
def close(job_id):
    reason = request.form.get("reason", "").strip() or "Closed by HR"
    _act(job_id, lambda j: adverts.close(j, reason, current_user), lambda j: f"{j.reference} closed on every channel.")
    return redirect(url_for("adverts.detail", job_id=job_id))


@bp.route("/<int:job_id>/readvertise", methods=["POST"])
@roles_required(*HR)
def readvertise(job_id):
    job = _act(job_id, lambda j: adverts.readvertise(j, current_user),
               lambda j: f"Cycle {j.cycle} drafted. Check the closing date and send it for approval.")
    if job.status == "Draft":
        return redirect(url_for("adverts.edit", job_id=job_id))
    return redirect(url_for("adverts.detail", job_id=job_id))


# -------------------------------------------------------------- JD library

@bp.route("/library")
@roles_required(*HR)
def library():
    rows = (JobDescriptionTemplate.query.options(joinedload(JobDescriptionTemplate.job_family))
            .order_by(JobDescriptionTemplate.active.desc(), JobDescriptionTemplate.title).all())
    return render_template("adverts/library.html", rows=rows, today=today())


@bp.route("/library/new", methods=["GET", "POST"])
@bp.route("/library/<int:template_id>/edit", methods=["GET", "POST"])
@roles_required(*HR)
def template_form(template_id=None):
    template = db.session.get(JobDescriptionTemplate, template_id) if template_id else JobDescriptionTemplate()
    if template is None:
        abort(404)
    form = request.form
    if request.method == "POST":
        values = {"title": form.get("title", "").strip(), "job_family_id": form.get("job_family_id", type=int) or None,
                  "description": form.get("description", "").strip(),
                  "required_skills": ", ".join(ats.split_skills(form.get("required_skills"))),
                  "preferred_skills": ", ".join(ats.split_skills(form.get("preferred_skills"))),
                  "min_experience": _int(form.get("min_experience")), "min_education": _int(form.get("min_education")),
                  "review_date": _date(form.get("review_date", "").strip()), "active": bool(form.get("active"))}
        values["ats_weights"], weight_errors = ats.parse_weights({k: form.get(f"w_{k}") for k in ats.WEIGHT_LABELS})
        try:
            if weight_errors:
                raise DomainError(" ".join(weight_errors))
            adverts.save_template(template, values, current_user)
            db.session.commit()
            flash("Job description saved.", "success")
            return redirect(url_for("adverts.library"))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    elif template.id is None:
        template.active = True
        template.review_date = date(today().year + 1, today().month, min(today().day, 28))
    weights = ({k: form.get(f"w_{k}", "") for k in ats.WEIGHT_LABELS} if form
               else template.ats_weights or ats.WEIGHTS)
    return render_template("adverts/library_form.html", template=template, form=form,
                           families=JobFamily.query.filter_by(active=True).order_by(JobFamily.name).all(),
                           education_levels=ats.EDUCATION_LEVELS, weights=weights, weight_labels=ats.WEIGHT_LABELS,
                           standard_weights=ats.WEIGHTS)
