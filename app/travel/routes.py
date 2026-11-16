"""Travel requests (14 Nov 2026, at the user's request): any staff member's requests, the form, the request page
(manager and Finance decisions, i-Travel's payment requisition, Finance marking it paid) and the i-Travel dashboard.
Business rules are in services/travel.py."""
from datetime import date, timedelta

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.datastructures import MultiDict

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import TravelRequest
from app.models.user import FINANCE, ITRAVEL
from app.services import audit, travel, workflow
from app.services.dates import today
from app.services.errors import DomainError

bp = Blueprint("travel", __name__, url_prefix="/travel")
DASHBOARD_ROLES = (ITRAVEL, FINANCE)


def _get(tr_id):
    tr = db.session.get(TravelRequest, tr_id) or abort(404)
    if not travel.can_view(current_user, tr):
        abort(403)
    return tr


def _form_values(form):
    """Posted form values back into the shape the template fills from (after an error)."""
    values = {key: form.get(key, "") for key, _label, _max in travel.CLIENT_FIELDS}
    values["seat"] = form.get("seat", "")
    for section, (_title, max_rows, fields) in travel.SECTIONS.items():
        columns = {key: form.getlist(f"{section}.{key}") for key, *_ in fields}
        count = min(max((len(v) for v in columns.values()), default=0), max_rows)
        values[section] = [{key: (columns[key][i] if i < len(columns[key]) else "") for key, *_ in fields}
                           for i in range(count)]
        values[section] = [r for r in values[section] if any(r.values())]
    return values


def _render_form(tr, values):
    return render_template("travel/form.html", tr=tr, values=values, sections=travel.SECTIONS, notes=travel.NOTES,
                           seats=travel.SEATS, problems=travel.traveller_problems(current_user),
                           today_iso=today().isoformat(), max_iso=(today() + timedelta(days=730)).isoformat())


@bp.route("")
@roles_required()
def index():
    return render_template("travel/index.html", requests=travel.mine(current_user), show=travel.show,
                           sees_dashboard=current_user.has_role(*DASHBOARD_ROLES))


@bp.route("/new", methods=["GET", "POST"])
@roles_required()
def new():
    if request.method == "POST":
        submit_now = request.form.get("action") == "submit"
        try:
            tr = travel.create(current_user, request.form, submit_now=submit_now)
            db.session.commit()
            flash(f"{tr.reference} sent to your manager for approval." if submit_now
                  else f"{tr.reference} saved as a draft.", "success")
            return redirect(url_for("travel.detail", tr_id=tr.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return _render_form(None, _form_values(request.form))
    return _render_form(None, travel.defaults_for(current_user))


@bp.route("/<int:tr_id>/edit", methods=["GET", "POST"])
@roles_required()
def edit(tr_id):
    tr = _get(tr_id)
    if not travel.can_edit(current_user, tr):
        flash(f"A {tr.status.lower()} travel request can't be changed.", "error")
        return redirect(url_for("travel.detail", tr_id=tr.id))
    if request.method == "POST":
        submit_now = request.form.get("action") == "submit"
        try:
            travel.save(tr, current_user, request.form, submit_now=submit_now)
            db.session.commit()
            flash(f"{tr.reference} sent to your manager for approval." if submit_now else "Draft saved.", "success")
            return redirect(url_for("travel.detail", tr_id=tr.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return _render_form(db.session.get(TravelRequest, tr_id), _form_values(request.form))
    return _render_form(tr, travel.values_of(tr))


@bp.route("/<int:tr_id>", methods=["GET", "POST"])
@roles_required()
def detail(tr_id):
    tr = _get(tr_id)
    if request.method == "POST":
        action, form = request.form.get("action"), request.form
        try:
            if action == "submit":
                travel.submit(tr, current_user)
                message = f"{tr.reference} sent to your manager for approval."
            elif action == "cancel":
                travel.cancel(tr, current_user, form.get("reason", ""))
                message = f"{tr.reference} cancelled."
            elif action == "send_to_finance":
                travel.send_to_finance(tr, current_user, form.get("amount"), form.get("supplier_reference"),
                                       form.get("payment_note"), request.files.get("invoice"))
                message = f"{tr.reference} sent to Finance for payment."
            elif action == "mark_paid":
                raw = form.get("paid_on", "")
                try:
                    paid_on = date.fromisoformat(raw) if raw else None
                except ValueError:
                    paid_on = None
                travel.mark_paid(tr, current_user, paid_on, form.get("payment_reference"))
                message = f"{tr.reference} marked as paid."
            else:
                abort(400)
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("travel.detail", tr_id=tr.id))
        except DomainError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            tr = db.session.get(TravelRequest, tr_id)
    approvals = workflow.history(travel.ENTITY, tr.id)
    payments = workflow.history(travel.PAYMENT_ENTITY, tr.id)
    my_step = None
    for instance in (approvals[:1] + payments[:1]):
        step = instance.current_step if instance.status == "Pending" else None
        if step and workflow.can_act(step, current_user):
            my_step = step
    return render_template("travel/detail.html", tr=tr, sections=travel.SECTIONS, show=travel.show, mask=travel.mask,
                           traveller_title=travel.TRAVELLER_TITLE, traveller_fields=travel.TRAVELLER_FIELDS,
                           traveller=tr.travellers[0] if tr.travellers else travel.traveller_for(tr.requester),
                           see_ids=travel.can_see_ids(current_user, tr), my_step=my_step,
                           approval=approvals[0] if approvals else None, payment=payments[0] if payments else None,
                           invoices=travel.invoices(tr), can_edit=travel.can_edit(current_user, tr),
                           can_cancel=travel.can_cancel(current_user, tr),
                           can_send=travel.can_send_to_finance(current_user, tr),
                           can_pay=travel.can_mark_paid(current_user, tr),
                           approver=workflow.manager_user(tr.requester), form=MultiDict())


@bp.route("/<int:tr_id>/form.pdf")
@roles_required()
def form_pdf(tr_id):
    tr = _get(tr_id)
    audit.record("travel.form_viewed", "travel_request", tr.id)
    db.session.commit()
    return Response(travel.form_pdf(tr), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{travel.pdf_name(tr)}"',
                             "X-Content-Type-Options": "nosniff"})


@bp.route("/dashboard")
@roles_required(*DASHBOARD_ROLES)
def dashboard():
    tab = request.args.get("tab", "to_book")
    tabs = {key: (label, statuses) for key, label, statuses in travel.DASHBOARD_TABS}
    if tab not in tabs:
        tab = "to_book"
    return render_template("travel/dashboard.html", tab=tab, tabs=travel.DASHBOARD_TABS,
                           rows=travel.by_status(*tabs[tab][1]), stats=travel.dashboard(), show=travel.show)
