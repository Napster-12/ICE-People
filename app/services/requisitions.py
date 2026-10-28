"""Requisition rules (REQ-TA-001–008): validation, submit, cancel, scoping. Every requisition is raised from a
vacant approved position (spec §15.3)."""
from datetime import date

from sqlalchemy import or_, select

from app.extensions import db
from app.models import (ApprovedPosition, CostCentre, Employee, Requisition, RequisitionVersion, WorkflowInstance,
                        WorkflowStep)
from app.models.user import COMPLIANCE, EXCO, EXECUTIVE_ROLES, FINANCE, GCOO, HOD, HR_ADMIN, HR_ROLES, LINE_MANAGER
from app.services import audit, budget, positions, workflow
from app.services.dates import now, today
from app.services.errors import DomainError, StateMachine
from app.services.notifications import notify
from app.services.refs import next_reference

FLOW = StateMachine("requisition", {
    "Draft": {"Submitted", "Cancelled"},
    "Submitted": {"In Approval", "Approved", "Cancelled"},
    "In Approval": {"Approved", "Returned", "Rejected", "Cancelled"},
    "Returned": {"Submitted", "Cancelled"},
    "Approved": {"Advertised", "Cancelled"},
    "Advertised": {"Interviewing", "Cancelled"},
    "Interviewing": {"Offer", "Advertised", "Cancelled"},
    "Offer": {"Filled", "Interviewing", "Cancelled"},
    "Filled": set(), "Rejected": set(), "Cancelled": set(),
})
EDITABLE = {"Draft", "Returned"}
CANCELLABLE_BY_ORIGINATOR = {"Draft", "Submitted", "In Approval", "Returned"}
CLOSABLE_UNFILLED = {"Approved", "Advertised", "Interviewing", "Offer"}

CREATE_ROLES = {LINE_MANAGER, HOD} | HR_ROLES
SEE_ALL_ROLES = HR_ROLES | {FINANCE, GCOO, EXCO, COMPLIANCE}
MIN_JUSTIFICATION = 50

FIELDS = ["title", "department_id", "cost_centre_id", "job_grade_id", "employment_type", "headcount_type",
          "replaced_employee_id", "contract_end_date", "required_start_date", "estimated_hours",
          "is_executive", "justification", "approved_position_id"]


class ValidationFailed(DomainError):
    def __init__(self, errors):
        super().__init__(" ".join(errors))
        self.errors = errors


def data_snapshot(req):
    out = {}
    for f in FIELDS + ["status", "ctc", "is_over_budget"]:
        v = getattr(req, f)
        out[f] = v.isoformat() if isinstance(v, date) else (str(v) if v is not None and not isinstance(v, (bool, int, str)) else v)
    return out


# ------------------------------------------------------------- validation

def validate_draft(req):
    errors = []
    if not req.approved_position_id:
        errors.append("Choose a vacant approved position. If the position isn't on the register, request an "
                      "ad-hoc position first.")
    return errors


def validate_submit(req):
    errors = positions.requisition_problems(req) if req.approved_position_id else validate_draft(req)
    if not req.department_id:
        errors.append("Choose a department.")
    if not req.cost_centre_id:
        errors.append("Choose a cost centre.")
    elif req.department_id:
        cc = db.session.get(CostCentre, req.cost_centre_id)
        if cc is None or cc.department_id != req.department_id:
            errors.append("The cost centre must belong to the chosen department.")
    if not req.job_grade_id:
        errors.append("Choose a job grade.")
    if req.employment_type not in ("Permanent", "Contract", "Casual"):
        errors.append("Choose an employment type.")
    if req.headcount_type not in ("New", "Replacement"):
        errors.append("Choose New or Replacement headcount.")
    if req.headcount_type == "Replacement" and not req.replaced_employee_id:
        errors.append("Choose the employee being replaced.")
    if not req.required_start_date:
        errors.append("Enter the required start date.")
    elif req.required_start_date <= today():
        errors.append("The required start date must be in the future.")
    if req.employment_type == "Contract":
        if not req.contract_end_date:
            errors.append("Contract roles need a contract end date.")
        elif req.required_start_date and req.contract_end_date <= req.required_start_date:
            errors.append("The contract end date must be after the start date.")
    if len((req.justification or "").strip()) < MIN_JUSTIFICATION:
        errors.append(f"The justification must be at least {MIN_JUSTIFICATION} characters.")
    return errors


# ----------------------------------------------------------------- saving

def apply_form(req, data, user):
    """Copy cleaned form data onto the requisition. The executive flag is only
    changed by roles allowed to see it."""
    for field in FIELDS:
        if field == "is_executive" and not user.has_role(*EXECUTIVE_ROLES):
            continue
        if field in data:
            setattr(req, field, data[field])
    position = db.session.get(ApprovedPosition, req.approved_position_id) if req.approved_position_id else None
    if position is not None:
        # The position decides the role; a position someone has left is a replacement.
        req.title = position.title
        req.department_id, req.cost_centre_id = position.department_id, position.cost_centre_id
        req.job_grade_id = position.job_grade_id
        req.headcount_type = "Replacement" if position.last_holder_id else "New"
        req.replaced_employee_id = position.last_holder_id
    if req.headcount_type != "Replacement":
        req.replaced_employee_id = None
    if req.employment_type != "Contract":
        req.contract_end_date = None
    if req.employment_type != "Casual":
        req.estimated_hours = None


def save(req, user):
    """Create or update a draft / returned requisition."""
    errors = validate_draft(req)
    if errors:
        raise ValidationFailed(errors)
    if req.id is None:
        req.reference = next_reference("REQ")
        req.originator_id = user.id
        req.status = "Draft"
        db.session.add(req)
        db.session.flush()
        audit.record("create", "requisition", req.id, after=data_snapshot(req))
    else:
        if req.status not in EDITABLE:
            raise DomainError("Only draft or returned requisitions can be edited.")
        before = getattr(req, "_loaded_snapshot", None) or {}
        b, a = audit.changes(before, data_snapshot(req))
        audit.record("update", "requisition", req.id, before=b, after=a)
    return req


def set_status(req, new, comment=None, notify_originator=True):
    FLOW.check(req.status, new)
    old = req.status
    req.status = new
    audit.record("status_change", "requisition", req.id, before={"status": old}, after={"status": new},
                 detail=comment)
    if notify_originator and req.originator:
        notify(req.originator, "requisition_status", link=f"/requisitions/{req.id}", ref=req.reference,
               title=req.title, status=new, comment=comment)


def workflow_context(req):
    return {
        "headcount_type": req.headcount_type,
        "is_over_budget": bool(req.is_over_budget),
        "grade": req.job_grade.grade if req.job_grade else 0,
        "is_executive": bool(req.is_executive),
        "employment_type": req.employment_type,
        "ctc": float(req.ctc or 0),
        "department": req.department.code if req.department else "",
        "department_id": req.department_id,
    }


def submit(req, user):
    if req.status not in EDITABLE:
        raise DomainError(f"A {req.status.lower()} requisition can't be submitted.")
    if user.id != req.originator_id:
        raise DomainError("Only the originator can submit this requisition.")
    db.session.flush()
    for rel in ("department", "cost_centre", "job_grade"):
        db.session.refresh(req, [rel])
    errors = validate_submit(req)
    if errors:
        raise ValidationFailed(errors)

    budget.snapshot_requisition(req)
    req.version += 1
    db.session.add(RequisitionVersion(requisition_id=req.id, version=req.version, data=data_snapshot(req),
                                      created_by_id=user.id, created_at=now()))
    req.submitted_at = now()
    set_status(req, "Submitted")
    instance = workflow.start("requisition", "requisition", req.id, req.originator, workflow_context(req),
                              department=req.department)
    if instance.status == "Pending":
        set_status(req, "In Approval", notify_originator=False)
    return instance


def cancel(req, user, reason=""):
    if req.status not in CANCELLABLE_BY_ORIGINATOR:
        raise DomainError("Approved requisitions can't be cancelled; HR can close them unfilled instead.")
    if user.id != req.originator_id and not user.has_role(HR_ADMIN):
        raise DomainError("Only the originator can cancel this requisition.")
    workflow.cancel(workflow.latest_instance("requisition", req.id))
    set_status(req, "Cancelled", comment=reason or None)
    req.closed_at = now()


def close_unfilled(req, user, reason):
    if req.status not in CLOSABLE_UNFILLED:
        raise DomainError("Only approved, open requisitions can be closed unfilled.")
    if not user.is_hr:
        raise DomainError("Only HR can close a requisition unfilled.")
    if not (reason or "").strip():
        raise DomainError("Give a reason for closing the requisition.")
    budget.release(req)
    positions.stop_recruitment(req.approved_position, req)
    set_status(req, "Cancelled", comment=f"Closed unfilled: {reason.strip()}")
    req.closed_at = now()


# ------------------------------------------------------- workflow handlers

def _req(instance):
    return db.session.get(Requisition, instance.entity_id)


def _on_approved(instance):
    req = _req(instance)
    set_status(req, "Approved")
    req.approved_at = now()
    positions.start_recruitment(req.approved_position, req)
    try:
        budget.commit(req)
    except DomainError as exc:
        audit.record("budget.commit_skipped", "requisition", req.id, detail=str(exc))


def _on_returned(instance):
    set_status(_req(instance), "Returned", notify_originator=False)


def _on_rejected(instance):
    set_status(_req(instance), "Rejected", notify_originator=False)


def _describe(instance):
    req = _req(instance)
    return {"ref": req.reference, "title": req.title, "link": f"/requisitions/{req.id}"}


workflow.register(
    "requisition", describe=_describe, on_approved=_on_approved, on_returned=_on_returned,
    on_rejected=_on_rejected,
    sample_context={"headcount_type": "New", "is_over_budget": False, "grade": 5, "is_executive": False,
                    "employment_type": "Permanent", "ctc": 0.0, "department": "HR",
                    "department_id": 1},
)


# ---------------------------------------------------------------- scoping

def _involved_ids(user):
    return (select(WorkflowInstance.entity_id).join(WorkflowStep)
            .where(WorkflowInstance.entity_type == "requisition",
                   or_(WorkflowStep.approver_id == user.id, WorkflowStep.assignee_id == user.id,
                       WorkflowStep.actor_id == user.id)))


def visible_query(user):
    q = Requisition.query
    if user.has_role(*SEE_ALL_ROLES):
        return q
    conditions = [Requisition.originator_id == user.id, Requisition.id.in_(_involved_ids(user))]
    if user.has_role(HOD) and user.department_id:
        conditions.append(Requisition.department_id == user.department_id)
    if user.has_role(LINE_MANAGER) and user.employee:
        report_user_ids = [e.user.id for e in user.employee.direct_reports if e.user]
        if report_user_ids:
            conditions.append(Requisition.originator_id.in_(report_user_ids))
    return q.filter(or_(*conditions))


def can_view(user, req):
    return visible_query(user).filter(Requisition.id == req.id).first() is not None


def can_edit(user, req):
    return req.status in EDITABLE and user.id == req.originator_id


def reference_data(user, req=None):
    keep = req.approved_position if req is not None else None
    choices = positions.raisable_query(user, keep=req).all()
    if keep is not None and keep not in choices:
        choices.insert(0, keep)
    return {
        "positions": choices,
        "employees": Employee.query.filter(Employee.status.notin_(["Exited", "Archived"]))
                                   .order_by(Employee.last_name).all(),
    }
