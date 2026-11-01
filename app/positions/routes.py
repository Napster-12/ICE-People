"""Approved positions register, ad-hoc position requests and the vacancy dashboard (spec §15.3)."""
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import ApprovedPosition, BusinessUnit, Department, Requisition
from app.models.org import POSITION_CHANGE_KINDS, POSITION_STATUSES
from app.services import budget, positions, workflow
from app.services.dates import to_decimal, today
from app.services.errors import DomainError
from app.services.positions import EDIT_ROLES, REQUEST_ROLES, VIEW_ROLES
from app.services.requisitions import CREATE_ROLES
from app.web import paginate

bp = Blueprint("positions", __name__, url_prefix="/positions")
ALL_VIEW = tuple(VIEW_ROLES | REQUEST_ROLES)


def _fy():
    return request.args.get("fy", type=int) or budget.financial_year_for(today())


def _years():
    current = budget.financial_year_for(today())
    years = {current, current + 1}
    years |= {fy for (fy,) in db.session.query(ApprovedPosition.financial_year).distinct()}
    return sorted(years)


def _get_visible(position_id):
    p = db.session.get(ApprovedPosition, position_id) or abort(404)
    if not positions.can_view(current_user, p):
        abort(403)
    return p


def _form_values(form):
    return {
        "title": form.get("title", ""),
        "department_id": form.get("department_id", type=int) or None,
        "cost_centre_id": form.get("cost_centre_id", type=int) or None,
        "job_grade_id": form.get("job_grade_id", type=int) or None,
        "branch_id": form.get("branch_id", type=int) or None,
        "job_family_id": form.get("job_family_id", type=int) or None,
        "reports_to_id": form.get("reports_to_id", type=int) or None,
        "budgeted_ctc": to_decimal(form.get("budgeted_ctc")),
        "budgeted_ctc_raw": form.get("budgeted_ctc", "").strip(),
        "minimum_requirements": form.get("minimum_requirements", ""),
        "critical": bool(form.get("critical")),
        "justification": form.get("justification", ""),
    }


def _reports_to_choices(exclude=None):
    q = ApprovedPosition.query.filter(ApprovedPosition.status.notin_(["Abolished", "Rejected"]))
    if exclude is not None:
        q = q.filter(ApprovedPosition.id != exclude.id)
    return q.order_by(ApprovedPosition.title, ApprovedPosition.position_number).all()


# -------------------------------------------------------------- register

@bp.route("/")
@roles_required(*VIEW_ROLES)
def index():
    fy, args = _fy(), request.args
    q = (positions.visible_query(current_user)
         .options(joinedload(ApprovedPosition.department), joinedload(ApprovedPosition.job_grade),
                  joinedload(ApprovedPosition.branch))
         .filter(ApprovedPosition.financial_year == fy))
    if args.get("status"):
        q = q.filter(ApprovedPosition.status == args["status"])
    if args.get("department_id", type=int):
        q = q.filter(ApprovedPosition.department_id == args.get("department_id", type=int))
    if args.get("business_unit_id", type=int):
        q = q.join(Department).filter(Department.business_unit_id == args.get("business_unit_id", type=int))
    if args.get("ad_hoc"):
        q = q.filter(ApprovedPosition.is_ad_hoc.is_(True))
    if args.get("q"):
        like = f"%{args['q'].strip()}%"
        q = q.filter(db.or_(ApprovedPosition.title.ilike(like), ApprovedPosition.position_number.ilike(like)))
    rows, pager = paginate(q.order_by(ApprovedPosition.position_number), 30)
    register = positions.register_for(fy)
    instance = workflow.latest_instance("position_register", register.id) if register else None
    my_step = None
    if instance and instance.status == "Pending" and instance.current_step \
            and workflow.can_act(instance.current_step, current_user):
        my_step = instance.current_step
    can_edit = current_user.has_role(*EDIT_ROLES)
    return render_template("positions/index.html", rows=rows, pager=pager, args=args, fy=fy, years=_years(),
                           fy_label=budget.fy_label, register=register, instance=instance, my_step=my_step,
                           planned=positions.planned_count(fy), editable=positions.register_editable(fy),
                           can_edit=can_edit, statuses=POSITION_STATUSES,
                           departments=Department.query.order_by(Department.name).all(),
                           business_units=BusinessUnit.query.order_by(BusinessUnit.name).all())


@bp.route("/new", methods=["GET", "POST"])
@roles_required(*EDIT_ROLES)
def new():
    fy = request.values.get("fy", type=int) or budget.financial_year_for(today())
    if request.method == "POST":
        try:
            p = positions.create_planned(_form_values(request.form), current_user, fy)
            db.session.commit()
            flash(f"{p.position_number} added to the {budget.fy_label(fy)} register.", "success")
            return redirect(url_for("positions.detail", position_id=p.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("positions/form.html", position=None, fy=fy, fy_label=budget.fy_label,
                           ref=positions.reference_data(), reports_to=_reports_to_choices(), values=request.form,
                           planned=True, ad_hoc=False)


@bp.route("/<int:position_id>/edit", methods=["GET", "POST"])
@roles_required(*EDIT_ROLES)
def edit(position_id):
    p = _get_visible(position_id)
    if request.method == "POST":
        try:
            positions.update(p, _form_values(request.form), current_user)
            db.session.commit()
            flash(f"{p.position_number} saved.", "success")
            return redirect(url_for("positions.detail", position_id=p.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("positions/form.html", position=p, fy=p.financial_year, fy_label=budget.fy_label,
                           ref=positions.reference_data(), reports_to=_reports_to_choices(p), values=request.form,
                           planned=p.status in ("Planned", "Returned"), ad_hoc=False)


@bp.route("/<int:position_id>")
@roles_required(*ALL_VIEW)
def detail(position_id):
    p = _get_visible(position_id)
    reqs = Requisition.query.filter_by(approved_position_id=p.id).order_by(Requisition.created_at.desc()).all()
    approvals = []
    if p.is_ad_hoc:
        approvals += [("Ad-hoc position request", i) for i in workflow.history("position", p.id)]
    for change in sorted(p.changes, key=lambda c: c.created_at, reverse=True):
        approvals += [(f"{change.kind}: {change.reason}", i) for i in workflow.history("position_change", change.id)]
    my_steps = [i.current_step for _label, i in approvals
                if i.status == "Pending" and i.current_step and workflow.can_act(i.current_step, current_user)]
    open_req = positions.open_requisition(p)
    return render_template(
        "positions/detail.html", p=p, reqs=reqs, approvals=approvals, my_steps=my_steps,
        fy_label=budget.fy_label, change_kinds=[k for k in POSITION_CHANGE_KINDS if p.status in positions.CHANGE_FROM[k]],
        pending_change=positions.pending_change(p), grades=positions.reference_data()["grades"],
        can_edit=current_user.has_role(*EDIT_ROLES) and p.status not in ("Abolished", "Rejected"),
        can_delete=current_user.has_role(*EDIT_ROLES) and p.status == "Planned"
        and positions.register_editable(p.financial_year),
        can_change=current_user.has_role(*EDIT_ROLES),
        can_resubmit=p.status == "Returned" and p.requested_by_id == current_user.id,
        can_raise=(p.status == "Vacant" and open_req is None and current_user.has_role(*CREATE_ROLES)
                   and positions.raisable_query(current_user).filter(ApprovedPosition.id == p.id).first() is not None),
        open_req=open_req)


@bp.route("/<int:position_id>/delete", methods=["POST"])
@roles_required(*EDIT_ROLES)
def delete(position_id):
    p = _get_visible(position_id)
    fy, number = p.financial_year, p.position_number
    positions.delete_planned(p, current_user)
    db.session.commit()
    flash(f"{number} deleted from the {budget.fy_label(fy)} register.", "success")
    return redirect(url_for("positions.index", fy=fy))


@bp.route("/<int:position_id>/change", methods=["POST"])
@roles_required(*EDIT_ROLES)
def request_change(position_id):
    p = _get_visible(position_id)
    kind = request.form.get("kind", "")
    positions.request_change(p, kind, request.form.get("reason", ""), current_user,
                             request.form.get("new_job_grade_id", type=int))
    db.session.commit()
    flash(f"{kind} of {p.position_number} sent for approval.", "success")
    return redirect(url_for("positions.detail", position_id=p.id))


@bp.route("/register/<int:fy>/submit", methods=["POST"])
@roles_required(*EDIT_ROLES)
def submit_register(fy):
    positions.submit_register(fy, current_user)
    db.session.commit()
    flash(f"The {budget.fy_label(fy)} register was sent to Finance and the Group HR Manager for approval.", "success")
    return redirect(url_for("positions.index", fy=fy))


@bp.route("/import", methods=["GET", "POST"])
@roles_required(*EDIT_ROLES)
def import_csv():
    errors = []
    if request.method == "POST":
        upload = request.files.get("file")
        if not upload or not upload.filename.lower().endswith(".csv"):
            errors = ["Choose a .csv file."]
        else:
            text = upload.read().decode("utf-8-sig", errors="replace")
            try:
                saved, errors = positions.import_csv(text, current_user)
            except DomainError as exc:
                saved, errors = 0, [str(exc)]
            if errors:
                db.session.rollback()
                flash(f"Nothing was imported: {len(errors)} row(s) need fixing.", "error")
            else:
                db.session.commit()
                flash(f"Imported {saved} planned position(s).", "success")
                return redirect(url_for("positions.index"))
    return render_template("positions/import.html", errors=errors, columns=positions.CSV_COLUMNS)


@bp.route("/import/template.csv")
@roles_required(*EDIT_ROLES)
def import_template():
    return Response(positions.csv_template(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=positions_template.csv"})


# --------------------------------------------------------------- ad hoc

@bp.route("/ad-hoc")
@roles_required(*ALL_VIEW)
def adhoc_list():
    q = (positions.visible_query(current_user).options(joinedload(ApprovedPosition.department))
         .filter(ApprovedPosition.is_ad_hoc.is_(True)))
    if request.args.get("status"):
        q = q.filter(ApprovedPosition.status == request.args["status"])
    rows, pager = paginate(q.order_by(ApprovedPosition.created_at.desc()), 25)
    return render_template("positions/adhoc_list.html", rows=rows, pager=pager, args=request.args,
                           can_request=current_user.has_role(*REQUEST_ROLES))


@bp.route("/ad-hoc/new", methods=["GET", "POST"])
@bp.route("/ad-hoc/<int:position_id>/edit", methods=["GET", "POST"])
@roles_required(*REQUEST_ROLES)
def adhoc_new(position_id=None):
    p = _get_visible(position_id) if position_id else None
    if p is not None and (p.status != "Returned" or p.requested_by_id != current_user.id):
        flash("Only the requester can change a returned ad-hoc position.", "error")
        return redirect(url_for("positions.detail", position_id=p.id))
    if request.method == "POST":
        try:
            instance = positions.request_ad_hoc(_form_values(request.form), current_user, p)
            db.session.commit()
            p = db.session.get(ApprovedPosition, instance.entity_id)
            flash(f"Ad-hoc position {p.position_number} sent for approval.", "success")
            return redirect(url_for("positions.detail", position_id=p.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("positions/form.html", position=p, fy=budget.financial_year_for(today()),
                           fy_label=budget.fy_label, ref=positions.reference_data(),
                           reports_to=_reports_to_choices(p), values=request.form, planned=True, ad_hoc=True,
                           defaults=positions.ad_hoc_defaults(current_user),
                           locked_department=positions.ad_hoc_department(current_user),
                           locked_reports_to=positions.ad_hoc_reports_to(current_user))


# ------------------------------------------------------------ dashboard

@bp.route("/dashboard")
@roles_required(*VIEW_ROLES)
def dashboard():
    fy = _fy()
    data = positions.vacancy_dashboard(current_user, fy, request.args.get("group_by", "business_unit"))
    if request.args.get("format") == "xlsx":
        return Response(positions.dashboard_workbook(data, fy),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=vacancies_{fy}.xlsx"})
    return render_template("positions/dashboard.html", data=data, fy=fy, years=_years(), fy_label=budget.fy_label,
                           groups=positions.GROUPS, today=today())
