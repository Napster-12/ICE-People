"""Requisitions (REQ-TA-001–008)."""
from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import ApprovedPosition, AuditLog, CostCentre, Department, Requisition
from app.models.org import EMPLOYMENT_TYPES
from app.models.requisition import REQUISITION_STATUSES
from app.models.user import EXECUTIVE_ROLES
from app.requisitions.forms import RequisitionForm
from app.services import adverts, budget, files, requisitions, workflow
from app.services.dates import today
from app.services.errors import DomainError
from app.services.requisitions import CREATE_ROLES, SEE_ALL_ROLES, ValidationFailed
from app.models.user import HOD, LINE_MANAGER
from app.web import flash_errors, paginate

bp = Blueprint("requisitions", __name__, url_prefix="/requisitions")
VIEW_ROLES = tuple(CREATE_ROLES | SEE_ALL_ROLES | {HOD, LINE_MANAGER})


def _get_visible(req_id):
    req = db.session.get(Requisition, req_id) or abort(404)
    if not requisitions.can_view(current_user, req):
        abort(403)
    return req


@bp.route("/")
@roles_required(*VIEW_ROLES)
def index():
    args = request.args
    q = (requisitions.visible_query(current_user)
         .options(joinedload(Requisition.department), joinedload(Requisition.job_grade),
                  joinedload(Requisition.originator)))
    if args.get("status"):
        q = q.filter(Requisition.status == args["status"])
    if args.get("department_id", type=int):
        q = q.filter(Requisition.department_id == args.get("department_id", type=int))
    if args.get("employment_type"):
        q = q.filter(Requisition.employment_type == args["employment_type"])
    if args.get("headcount_type"):
        q = q.filter(Requisition.headcount_type == args["headcount_type"])
    for key, op in (("date_from", "ge"), ("date_to", "le")):
        if args.get(key):
            try:
                d = date.fromisoformat(args[key])
            except ValueError:
                continue
            q = q.filter(Requisition.created_at >= d if op == "ge"
                         else Requisition.created_at < date.fromordinal(d.toordinal() + 1))
    if args.get("q"):
        like = f"%{args['q'].strip()}%"
        q = q.filter(db.or_(Requisition.title.ilike(like), Requisition.reference.ilike(like)))
    rows, pager = paginate(q.order_by(Requisition.created_at.desc()), 20)
    return render_template("requisitions/index.html", rows=rows, pager=pager, args=args,
                           statuses=REQUISITION_STATUSES, employment_types=EMPLOYMENT_TYPES,
                           departments=Department.query.order_by(Department.name).all(),
                           can_create=current_user.has_role(*CREATE_ROLES))


def _save_attachments(form, req):
    for upload in form.attachments.data or []:
        if upload and getattr(upload, "filename", ""):
            files.save_upload(upload, "requisition", req.id, current_user)


def _handle_form(form, req, ref):
    """Save as draft or submit, depending on the button pressed. Returns a redirect or None."""
    action = request.form.get("action", "draft")
    data = form.cleaned()
    if data["approved_position_id"] and data["approved_position_id"] not in {p.id for p in ref["positions"]}:
        flash("That position isn't vacant or isn't one you can raise a requisition for.", "error")
        return None
    if req.id is not None:
        req._loaded_snapshot = requisitions.data_snapshot(req)
    requisitions.apply_form(req, data, current_user)
    try:
        requisitions.save(req, current_user)
        _save_attachments(form, req)
        if action == "submit":
            requisitions.submit(req, current_user)
            message = f"{req.reference} submitted for approval."
            if req.is_over_budget:
                flash("This requisition is over the cost centre's available budget. Finance will see this.", "info")
        else:
            message = f"{req.reference} saved as a draft."
        db.session.commit()
        flash(message, "success")
        return redirect(url_for("requisitions.detail", req_id=req.id))
    except ValidationFailed as exc:
        db.session.rollback()
        flash_errors(exc.errors)
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return None


@bp.route("/new", methods=["GET", "POST"])
@roles_required(*CREATE_ROLES)
def new():
    ref = requisitions.reference_data(current_user)
    form = RequisitionForm()
    if request.method == "GET" and request.args.get("position", type=int):
        form.approved_position_id.data = request.args.get("position", type=int)
    form.set_choices(ref)
    if form.validate_on_submit():
        result = _handle_form(form, Requisition(), ref)
        if result:
            return result
    elif request.method == "POST":
        flash_errors([f"{getattr(form, k).label.text}: {', '.join(v)}" for k, v in form.errors.items()])
    return render_template("requisitions/form.html", form=form, req=None, ref=ref,
                           show_exec=current_user.has_role(*EXECUTIVE_ROLES))


@bp.route("/<int:req_id>/edit", methods=["GET", "POST"])
@roles_required(*CREATE_ROLES)
def edit(req_id):
    req = _get_visible(req_id)
    if not requisitions.can_edit(current_user, req):
        flash("Only the originator can edit a draft or returned requisition.", "error")
        return redirect(url_for("requisitions.detail", req_id=req.id))
    ref = requisitions.reference_data(current_user, req)
    form = RequisitionForm(obj=req)
    form.set_choices(ref)
    if form.validate_on_submit():
        result = _handle_form(form, req, ref)
        if result:
            return result
    elif request.method == "POST":
        flash_errors([f"{getattr(form, k).label.text}: {', '.join(v)}" for k, v in form.errors.items()])
    return render_template("requisitions/form.html", form=form, req=req, ref=ref,
                           show_exec=current_user.has_role(*EXECUTIVE_ROLES))


@bp.route("/<int:req_id>")
@roles_required(*VIEW_ROLES)
def detail(req_id):
    req = _get_visible(req_id)
    instances = workflow.history("requisition", req.id)
    current = instances[0] if instances else None
    my_step = None
    if current and current.status == "Pending":
        step = current.current_step
        if step and workflow.can_act(step, current_user):
            my_step = step
    preview = None
    if req.status in requisitions.EDITABLE and req.approved_position and req.employment_type:
        try:
            fy = budget.financial_year_for(req.required_start_date or today())
            ctc = budget.calculate_ctc(req.approved_position, req.employment_type, req.required_start_date,
                                       req.contract_end_date)
            available = budget.available_budget(req.cost_centre_id, fy) if req.cost_centre_id else None
            preview = {"ctc": ctc, "available": available, "fy": fy, "unbudgeted": ctc is None,
                       "over": ctc is not None and available is not None and ctc > available}
        except DomainError:
            preview = None
    timeline = (AuditLog.query.filter_by(entity="requisition", entity_id=str(req.id))
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).all())
    return render_template("requisitions/detail.html", req=req, instances=instances, current=current,
                           my_step=my_step, preview=preview, timeline=timeline,
                           attachments=files.files_for("requisition", req.id),
                           can_edit=requisitions.can_edit(current_user, req),
                           can_cancel=(req.status in requisitions.CANCELLABLE_BY_ORIGINATOR
                                       and current_user.id == req.originator_id),
                           can_close=req.status in requisitions.CLOSABLE_UNFILLED and current_user.is_hr,
                           show_exec=current_user.has_role(*EXECUTIVE_ROLES), fy_label=budget.fy_label,
                           advert=adverts.advert_for(req))


@bp.route("/<int:req_id>/submit", methods=["POST"])
@roles_required(*CREATE_ROLES)
def submit(req_id):
    req = _get_visible(req_id)
    try:
        requisitions.submit(req, current_user)
        db.session.commit()
        flash(f"{req.reference} submitted for approval.", "success")
    except ValidationFailed as exc:
        db.session.rollback()
        flash_errors(exc.errors)
    return redirect(url_for("requisitions.detail", req_id=req_id))


@bp.route("/<int:req_id>/cancel", methods=["POST"])
@roles_required(*VIEW_ROLES)
def cancel(req_id):
    req = _get_visible(req_id)
    requisitions.cancel(req, current_user, request.form.get("reason", ""))
    db.session.commit()
    flash(f"{req.reference} cancelled.", "success")
    return redirect(url_for("requisitions.detail", req_id=req_id))


@bp.route("/<int:req_id>/close", methods=["POST"])
@roles_required(*VIEW_ROLES)
def close(req_id):
    req = _get_visible(req_id)
    requisitions.close_unfilled(req, current_user, request.form.get("reason", ""))
    db.session.commit()
    flash(f"{req.reference} closed unfilled and its budget released.", "success")
    return redirect(url_for("requisitions.detail", req_id=req_id))


@bp.route("/<int:req_id>/attachments", methods=["POST"])
@roles_required(*VIEW_ROLES)
def upload(req_id):
    req = _get_visible(req_id)
    if not requisitions.can_edit(current_user, req):
        abort(403)
    uploads = [f for f in request.files.getlist("attachments") if f and f.filename]
    if not uploads:
        flash("Choose at least one file.", "error")
    for f in uploads:
        files.save_upload(f, "requisition", req.id, current_user)
    db.session.commit()
    if uploads:
        flash(f"{len(uploads)} attachment(s) added.", "success")
    return redirect(url_for("requisitions.detail", req_id=req_id))


# ------------------------------------------------------------- form APIs

@bp.route("/api/cost-centres")
@roles_required(*CREATE_ROLES)
def api_cost_centres():
    dept_id = request.args.get("department_id", type=int)
    rows = CostCentre.query.filter_by(department_id=dept_id, active=True).order_by(CostCentre.code).all()
    return jsonify([{"id": c.id, "label": str(c)} for c in rows])


@bp.route("/api/budget-check")
@roles_required(*CREATE_ROLES)
def api_budget_check():
    """Live CTC and availability preview while filling in the form."""
    from app.services.dates import format_money
    position = db.session.get(ApprovedPosition, request.args.get("position_id", type=int) or 0)
    cc_id = request.args.get("cost_centre_id", type=int)

    def as_date(key):
        try:
            return date.fromisoformat(request.args.get(key, ""))
        except ValueError:
            return None
    start, end = as_date("start"), as_date("end")
    try:
        ctc = budget.calculate_ctc(position, request.args.get("employment_type"), start, end)
    except DomainError as exc:
        return jsonify({"ok": False, "message": str(exc)})
    if ctc is None:
        return jsonify({"ok": False, "message": budget.UNBUDGETED_NOTE})
    fy = budget.financial_year_for(start or today())
    available = budget.available_budget(cc_id, fy) if cc_id else None
    return jsonify({"ok": True, "ctc": format_money(ctc), "fy": budget.fy_label(fy),
                    "available": format_money(available) if available is not None else None,
                    "over": bool(available is not None and ctc > available)})
