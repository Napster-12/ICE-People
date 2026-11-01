"""Approvals inbox, approve / return / reject, delegation and the approvals dashboard (REQ-AP-001–008)."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import Delegation, LeaveEntry, User, WorkflowInstance, WorkflowStep
from app.models.user import IT
from app.services import audit, workflow
from app.services.calendar import business_days_between
from app.services.dates import format_date, now, today
from app.services.errors import DomainError
from app.services.notifications import notify
from app.web import paginate

bp = Blueprint("approvals", __name__, url_prefix="/approvals")

AGEING_BUCKETS = [("0–2 days", 0, 2), ("3–5 days", 3, 5), ("6–10 days", 6, 10), ("Over 10 days", 11, 10_000)]


def _rows(steps):
    at = now()
    out = []
    for s in steps:
        info = workflow.describe(s.instance)
        out.append({"step": s, "info": info, "age": business_days_between(s.activated_at, at),
                    "overdue": bool(s.due_at and at > s.due_at),
                    "delegated_to_me": s.assignee_id == current_user.id and s.approver_id != current_user.id,
                    "delegated_away": s.approver_id == current_user.id and s.assignee_id != current_user.id})
    return out


@bp.route("/")
@roles_required()
def inbox():
    pending = _rows(workflow.pending_for(current_user))
    done = (WorkflowStep.query.options(joinedload(WorkflowStep.instance))
            .filter(WorkflowStep.actor_id == current_user.id).order_by(WorkflowStep.acted_at.desc()))
    done, pager = paginate(done, 15)
    done = [{"step": s, "info": workflow.describe(s.instance)} for s in done]
    return render_template("approvals/inbox.html", pending=pending, done=done, pager=pager)


@bp.route("/steps/<int:step_id>/act", methods=["POST"])
@roles_required()
def act(step_id):
    step = db.session.get(WorkflowStep, step_id) or abort(404)
    action = request.form.get("action", "")
    try:
        workflow.act(step, current_user, action, request.form.get("comment", ""))
        db.session.commit()
        verb = {"approve": "approved", "return": "returned for revision", "reject": "rejected"}[action]
        flash(f"{workflow.describe(step.instance)['ref']} {verb}.", "success")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    target = request.form.get("next") or ""
    return redirect(target if target.startswith("/") and not target.startswith("//") else url_for("approvals.inbox"))


# ------------------------------------------------------------ delegation

@bp.route("/delegations", methods=["GET", "POST"])
@roles_required()
def delegations():
    if request.method == "POST":
        try:
            delegate = db.session.get(User, request.form.get("delegate_id", type=int) or 0)
            start = date.fromisoformat(request.form.get("start_date", ""))
            end = date.fromisoformat(request.form.get("end_date", ""))
        except ValueError:
            delegate, start, end = None, None, None
        errors = []
        if delegate is None or not delegate.active:
            errors.append("Choose a delegate.")
        elif delegate.id == current_user.id:
            errors.append("You can't delegate to yourself.")
        if start is None or end is None:
            errors.append("Enter a start and end date.")
        elif end < start:
            errors.append("The end date must be on or after the start date.")
        elif end < today():
            errors.append("The delegation must not be entirely in the past.")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            d = Delegation(user_id=current_user.id, delegate_id=delegate.id, start_date=start, end_date=end,
                           reason=request.form.get("reason", "").strip()[:255])
            db.session.add(d)
            db.session.flush()
            audit.record("delegation.create", "delegation", d.id,
                         after={"delegate": delegate.username, "start": start.isoformat(), "end": end.isoformat()})
            # Re-route steps already waiting for me if the delegation covers today.
            if start <= today() <= end:
                for s in workflow.pending_steps_query().filter(WorkflowStep.assignee_id == current_user.id).all():
                    s.assignee_id = delegate.id
                    s.routing_note = ((s.routing_note or "") + f" Delegated by {current_user.full_name}.").strip()
            notify(delegate, "delegation_set", link="/approvals/", user=current_user.full_name,
                   start=format_date(start), end=format_date(end))
            db.session.commit()
            flash(f"Approvals delegated to {delegate.full_name} from {format_date(start)} to {format_date(end)}.",
                  "success")
            return redirect(url_for("approvals.delegations"))
    mine = Delegation.query.filter_by(user_id=current_user.id).order_by(Delegation.start_date.desc()).all()
    to_me = Delegation.query.filter_by(delegate_id=current_user.id, active=True).filter(
        Delegation.end_date >= today()).all()
    leave = []
    if current_user.employee:
        leave = LeaveEntry.query.filter(LeaveEntry.employee_id == current_user.employee.id,
                                        LeaveEntry.end_date >= today()).order_by(LeaveEntry.start_date).all()
    users = User.query.filter(User.active.is_(True), User.id != current_user.id).order_by(User.full_name).all()
    return render_template("approvals/delegations.html", mine=mine, to_me=to_me, users=users, leave=leave,
                           today=today())


@bp.route("/delegations/<int:delegation_id>/end", methods=["POST"])
@roles_required()
def end_delegation(delegation_id):
    d = db.session.get(Delegation, delegation_id) or abort(404)
    if d.user_id != current_user.id:
        abort(403)
    d.active = False
    # Hand back steps that are still with the delegate.
    for s in workflow.pending_steps_query().filter(WorkflowStep.approver_id == current_user.id,
                                                   WorkflowStep.assignee_id == d.delegate_id).all():
        s.assignee_id = current_user.id
    audit.record("delegation.end", "delegation", d.id)
    db.session.commit()
    flash("Delegation ended. Waiting approvals are back with you.", "success")
    return redirect(url_for("approvals.delegations"))


# ------------------------------------------------------------- dashboard

@bp.route("/dashboard")
@roles_required(IT)
def dashboard():
    steps = (workflow.pending_steps_query()
             .options(joinedload(WorkflowStep.assignee), joinedload(WorkflowStep.instance))
             .order_by(WorkflowStep.activated_at).all())
    rows = _rows(steps)
    by_approver = {}
    for r in rows:
        name = r["step"].assignee.full_name if r["step"].assignee else "Unassigned"
        entry = by_approver.setdefault(name, {"count": 0, "overdue": 0, "oldest": 0})
        entry["count"] += 1
        entry["overdue"] += int(r["overdue"])
        entry["oldest"] = max(entry["oldest"], r["age"])
    ageing = [{"label": label, "count": sum(1 for r in rows if lo <= r["age"] <= hi)}
              for label, lo, hi in AGEING_BUCKETS]
    status_counts = dict(db.session.query(WorkflowInstance.status, db.func.count())
                         .group_by(WorkflowInstance.status).all())
    if request.args.get("approver"):
        rows = [r for r in rows if (r["step"].assignee.full_name if r["step"].assignee else "Unassigned")
                == request.args["approver"]]
    rows, pager = paginate(rows, 25)
    return render_template("approvals/dashboard.html", rows=rows, pager=pager, ageing=ageing,
                           by_approver=sorted(by_approver.items(), key=lambda kv: -kv[1]["count"]),
                           status_counts=status_counts)
