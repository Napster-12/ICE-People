"""Generic approval workflow engine.

Requisitions, adverts, offers, the competency framework and waivers all use it.
Each workflow type registers handlers (what to do on approve / return / reject)
and a `describe` function (reference, title and link used in notifications).

Chains come from RoutingRule rows: each rule has a level, an approver (a role
name or a special resolver such as the originator's line manager), a condition
evaluated against the item's context, and an SLA in business days.
"""
from dataclasses import dataclass
from typing import Callable

from app.extensions import db
from app.integrations import get_adapter
from app.models import Delegation, Role, RoutingRule, User, WorkflowInstance, WorkflowStep
from app.models.user import EXCO, GCOO, HR_ADMIN
from app.models.workflow import GCOO_OR_EXCO, LINE_MANAGER_OR_HOD, ORIGINATOR_MANAGER
from app.services import audit, settings
from app.services.calendar import add_business_days, business_hours_between
from app.services.conditions import evaluate
from app.services.dates import format_date, format_datetime, now
from app.services.errors import DomainError
from app.services.notifications import notify

ACTIONS = {"approve": "Approved", "return": "Returned", "reject": "Rejected"}


@dataclass
class Handlers:
    describe: Callable          # instance -> {"ref": .., "title": .., "link": ..}
    on_approved: Callable       # instance -> None
    on_returned: Callable
    on_rejected: Callable
    sample_context: dict        # used to validate routing-rule conditions


HANDLERS: dict[str, Handlers] = {}


def register(workflow_type, **kwargs):
    HANDLERS[workflow_type] = Handlers(**kwargs)


# ------------------------------------------------------------ people lookup

def _active(user):
    return user if user is not None and user.active else None


def manager_user(user):
    """The nearest manager up the reporting line who has an active user account."""
    emp = user.employee if user else None
    current, hops = (emp.manager if emp else None), 0
    while current is not None and hops < 10:
        if _active(current.user):
            return current.user
        current, hops = current.manager, hops + 1
    return None


def hod_user(department):
    if department is not None and department.hod is not None:
        return _active(department.hod.user)
    return None


def users_with_role(role, exclude=None):
    q = User.query.filter(User.active.is_(True), User.roles.any(Role.name == role))
    if exclude is not None:
        q = q.filter(User.id != exclude.id)
    return q.order_by(User.id).all()


def first_user_with_role(role, department_id=None, exclude=None):
    candidates = users_with_role(role, exclude=exclude)
    if department_id:
        same = [u for u in candidates if u.department_id == department_id]
        if same:
            return same[0]
    return candidates[0] if candidates else None


def resolve_approver(rule_value, originator, department):
    """Who a rule points at, before delegation. Returns (user, routing_note)."""
    note = None
    if rule_value == LINE_MANAGER_OR_HOD:
        user = manager_user(originator) or hod_user(department)
    elif rule_value == ORIGINATOR_MANAGER:
        user = manager_user(originator)
    elif rule_value == GCOO_OR_EXCO:
        user = first_user_with_role(GCOO, exclude=originator) or first_user_with_role(EXCO, exclude=originator)
    else:
        user = first_user_with_role(rule_value, department.id if department else None)

    # No self-approval: route to the originator's manager instead.
    if user is not None and user.id == originator.id:
        alternative = manager_user(originator)
        if alternative is None and not rule_value.startswith("@"):
            alternative = first_user_with_role(rule_value, exclude=originator)
        user = alternative
        note = "Originator can't approve their own request; routed to their manager."
    if user is None:
        user = first_user_with_role(HR_ADMIN, exclude=originator)
        note = (note + " " if note else "") + "No approver found; routed to HR Admin."
    return user, note


def active_delegation(user, on_date):
    return (Delegation.query.filter(Delegation.user_id == user.id, Delegation.active.is_(True),
                                    Delegation.start_date <= on_date, Delegation.end_date >= on_date)
            .order_by(Delegation.id.desc()).first())


def apply_delegation(user, originator, on_date):
    """Delegate (or the manager of an approver on leave) who should act. Returns (user, note)."""
    delegation = active_delegation(user, on_date)
    if delegation and _active(delegation.delegate):
        target, note = delegation.delegate, f"Delegated by {user.full_name}."
    elif get_adapter("leave").is_on_leave(user.employee, on_date) and manager_user(user):
        target, note = manager_user(user), f"{user.full_name} is on leave; routed to their manager."
    else:
        return user, None
    if target.id == originator.id:
        return manager_user(originator) or user, note + " Delegate is the originator; routed to their manager."
    return target, note


# ------------------------------------------------------------------ engine

def build_chain(workflow_type, context):
    rules = (RoutingRule.query.filter_by(workflow_type=workflow_type, active=True)
             .order_by(RoutingRule.level, RoutingRule.id).all())
    return [r for r in rules if evaluate(r.condition, context)]


def start(workflow_type, entity_type, entity_id, originator, context, department=None):
    previous = WorkflowInstance.query.filter_by(entity_type=entity_type, entity_id=entity_id).count()
    instance = WorkflowInstance(workflow_type=workflow_type, entity_type=entity_type, entity_id=entity_id,
                                originator_id=originator.id, originator=originator, context=context,
                                round=previous + 1, status="Pending")
    db.session.add(instance)
    for rule in build_chain(workflow_type, context):
        instance.steps.append(WorkflowStep(level=rule.level, name=rule.name, approver_rule=rule.approver,
                                           sla_days=rule.sla_days, status="Waiting"))
    db.session.flush()
    instance._department = department
    if instance.steps:
        _activate(instance.steps[0], instance, department)
    else:
        _complete(instance, "Approved")
    return instance


def _department_for(instance):
    dept = getattr(instance, "_department", None)
    if dept is None:
        from app.models import Department
        dept_id = (instance.context or {}).get("department_id")
        dept = db.session.get(Department, dept_id) if dept_id else None
    return dept


def _activate(step, instance, department=None):
    at = now()
    approver, note = resolve_approver(step.approver_rule, instance.originator, department or _department_for(instance))
    assignee, delegation_note = apply_delegation(approver, instance.originator, at.date()) if approver else (None, None)
    step.status = "Pending"
    step.activated_at = at
    step.due_at = add_business_days(at, step.sla_days)
    step.approver_id = approver.id if approver else None
    step.assignee_id = assignee.id if assignee else None
    step.routing_note = " ".join(n for n in (note, delegation_note) if n) or None
    info = describe(instance)
    if assignee:
        notify(assignee, "approval_requested", link=info["link"], ref=info["ref"], title=info["title"],
               originator=instance.originator.full_name, level=step.level, step=step.name,
               due=format_datetime(step.due_at))


def describe(instance):
    handlers = HANDLERS.get(instance.workflow_type)
    if handlers is None:
        return {"ref": f"{instance.entity_type} #{instance.entity_id}", "title": "", "link": None}
    return handlers.describe(instance)


def can_act(step, user):
    return (step.status == "Pending" and user is not None
            and user.id in {step.assignee_id, step.approver_id})


def act(step, user, action, comment):
    if action not in ACTIONS:
        raise DomainError("Choose approve, return for revision or reject.")
    if not (comment or "").strip():
        raise DomainError("A comment is required for every approval action.")
    if step.instance.status != "Pending" or step.status != "Pending":
        raise DomainError("This approval step is no longer waiting for a decision.")
    if not can_act(step, user):
        raise DomainError("You are not the approver for this step.")

    instance = step.instance
    step.status = ACTIONS[action]
    step.action = action
    step.comment = comment.strip()
    step.actor_id = user.id
    step.acted_at = now()
    audit.record("approval." + action, instance.entity_type, instance.entity_id,
                 after={"level": step.level, "step": step.name, "approver_id": step.approver_id,
                        "actor_id": user.id, "comment": step.comment, "round": instance.round})

    info = describe(instance)
    if action == "approve":
        nxt = next((s for s in instance.steps if s.status == "Waiting"), None)
        if nxt is not None:
            _activate(nxt, instance)
            return instance
        _complete(instance, "Approved")
    else:
        for s in instance.steps:
            if s.status == "Waiting":
                s.status = "Cancelled"
        notify(instance.originator, "approval_outcome", link=info["link"], ref=info["ref"], title=info["title"],
               actor=user.full_name, outcome="returned for revision" if action == "return" else "rejected",
               level=step.level, comment=step.comment)
        _complete(instance, ACTIONS[action])
    return instance


def _complete(instance, status):
    instance.status = status
    instance.completed_at = now()
    handlers = HANDLERS.get(instance.workflow_type)
    if handlers is None:
        return
    {"Approved": handlers.on_approved, "Returned": handlers.on_returned,
     "Rejected": handlers.on_rejected}[status](instance)


def cancel(instance):
    if instance is None or instance.status != "Pending":
        return
    for s in instance.steps:
        if s.status in ("Waiting", "Pending"):
            s.status = "Cancelled"
    instance.status = "Cancelled"
    instance.completed_at = now()


# ----------------------------------------------------------------- queries

def latest_instance(entity_type, entity_id):
    return (WorkflowInstance.query.filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(WorkflowInstance.round.desc()).first())


def history(entity_type, entity_id):
    return (WorkflowInstance.query.filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(WorkflowInstance.round.desc()).all())


def pending_steps_query():
    return (WorkflowStep.query.join(WorkflowInstance)
            .filter(WorkflowStep.status == "Pending", WorkflowInstance.status == "Pending"))


def pending_for(user):
    return (pending_steps_query()
            .filter(db.or_(WorkflowStep.assignee_id == user.id, WorkflowStep.approver_id == user.id))
            .order_by(WorkflowStep.due_at).all())


def pending_count(user):
    return (pending_steps_query()
            .filter(db.or_(WorkflowStep.assignee_id == user.id, WorkflowStep.approver_id == user.id)).count())


# --------------------------------------------------------------- SLA checks

def run_sla_checks(at=None):
    """Remind inactive approvers and escalate steps past their SLA. Returns counts."""
    at = at or now()
    reminder_hours = settings.get("sla_reminder_hours", float)
    reminded = escalated = 0
    for step in pending_steps_query().all():
        instance = step.instance
        info = describe(instance)
        if step.due_at and at > step.due_at and step.escalated_at is None:
            previous = step.assignee
            target = manager_user(previous) if previous else None
            if target is None or (previous and target.id == previous.id):
                target = first_user_with_role(HR_ADMIN, exclude=previous)
            if target is None:
                continue
            step.escalated_from = previous
            step.assignee = target
            step.escalated_at = at
            audit.record("approval.escalated", instance.entity_type, instance.entity_id,
                         before={"assignee_id": step.escalated_from_id}, after={"assignee_id": target.id},
                         detail=f"Level {step.level} passed SLA due {format_datetime(step.due_at)}")
            notify(target, "approval_escalated", link=info["link"], ref=info["ref"], title=info["title"],
                   previous=previous.full_name if previous else "the previous approver")
            if previous:
                notify(previous, "approval_escalated", link=info["link"], ref=info["ref"], title=info["title"],
                       previous="you")
            escalated += 1
            continue
        last_touch = step.reminded_at or step.activated_at
        if step.reminded_at is None and last_touch and business_hours_between(last_touch, at) >= reminder_hours:
            step.reminded_at = at
            notify(step.assignee, "approval_reminder", link=info["link"], ref=info["ref"], title=info["title"],
                   since=format_date(step.activated_at), due=format_datetime(step.due_at))
            reminded += 1
    return {"reminded": reminded, "escalated": escalated}
