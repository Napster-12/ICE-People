"""Phase 3: approval routing, no self-approval, delegation, return/resubmit, SLA reminders and escalation."""
import itertools
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import BudgetLine, Delegation, JobGrade, LeaveEntry, Notification, WorkflowStep
from app.services import workflow
from app.services.dates import now, today
from app.services.errors import DomainError
from tests.conftest import make_requisition, user


def chain_names(req):
    inst = workflow.latest_instance("requisition", req.id)
    return [s.name for s in inst.steps]


CHAIN = ["Line manager", "Finance / Budget Controller", "Group HR Manager", "GCOO / Exco"]


@pytest.mark.parametrize("new,over,grade,executive", list(itertools.product([False, True], [False, True],
                                                                             [4, 9], [False, True])))
def test_every_requisition_follows_the_same_chain(app, new, over, grade, executive):
    """Decided 28 Oct 2026: line manager → Finance → Group HR Manager → GCOO or Exco, whatever the request."""
    if over:
        for line in BudgetLine.query.all():
            line.amount = Decimal("1000")
    fields = {"job_grade_id": JobGrade.query.filter_by(grade=grade).first().id, "is_executive": executive}
    if new:
        fields.update(headcount_type="New", replaced_employee_id=None)
    req = make_requisition(user("hod"), **fields)   # HOD may set the executive flag
    assert chain_names(req) == CHAIN
    assert req.status == "In Approval"
    assert req.is_over_budget is over


def test_last_step_goes_to_exco_when_there_is_no_gcoo(app):
    req = make_requisition(user("employee"))
    inst = workflow.latest_instance("requisition", req.id)
    for actor in ("linemanager", "finance", "grouphr"):
        workflow.act(inst.current_step, user(actor), "approve", "ok")
    assert inst.current_step.assignee.username == "gcoo"
    user("gcoo").active = False
    req2 = make_requisition(user("employee"))
    inst2 = workflow.latest_instance("requisition", req2.id)
    for actor in ("linemanager", "finance", "grouphr"):
        workflow.act(inst2.current_step, user(actor), "approve", "ok")
    assert inst2.current_step.assignee.username == "exco"


def test_gcoo_cannot_approve_own_requisition_exco_does(app):
    req = make_requisition(user("gcoo"))
    inst = workflow.latest_instance("requisition", req.id)
    steps = {s.level: s for s in inst.steps}
    assert steps[1].assignee.username == "hod"              # GCOO has no manager: the position's HOD
    for actor in ("hod", "finance", "grouphr"):
        workflow.act(inst.current_step, user(actor), "approve", "ok")
    assert inst.current_step.assignee.username == "exco"


def test_level_one_goes_to_line_manager_then_hod(app):
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    assert step.assignee.username == "linemanager"
    req2 = make_requisition(user("linemanager"))
    assert workflow.latest_instance("requisition", req2.id).current_step.assignee.username == "hod"


def test_no_self_approval_routes_to_originators_manager(app):
    # Finance raises a requisition: level 2 would be Finance themselves.
    req = make_requisition(user("finance"))
    inst = workflow.latest_instance("requisition", req.id)
    workflow.act(inst.current_step, user("gcoo"), "approve", "OK from line manager")
    step2 = inst.current_step
    assert step2.name == "Finance / Budget Controller"
    assert step2.assignee.username == "gcoo"               # Finance's manager
    assert "can't approve their own" in step2.routing_note
    with pytest.raises(DomainError):
        workflow.act(step2, user("finance"), "approve", "self")


def test_full_approval_commits_budget(app):
    req = make_requisition(user("linemanager"), headcount_type="New", replaced_employee_id=None)
    inst = workflow.latest_instance("requisition", req.id)
    for actor in ("hod", "finance", "grouphr", "gcoo"):
        workflow.act(inst.current_step, user(actor), "approve", f"Approved by {actor}")
    assert inst.status == "Approved" and req.status == "Approved"
    assert req.approved_position.status == "In recruitment"
    assert Decimal(req.committed_amount) == Decimal(req.ctc)
    assert Decimal(req.budget_line.committed) == Decimal(req.ctc)


def test_comment_is_mandatory_and_only_assignee_can_act(app):
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    with pytest.raises(DomainError, match="comment"):
        workflow.act(step, user("linemanager"), "approve", "  ")
    with pytest.raises(DomainError, match="not the approver"):
        workflow.act(step, user("finance"), "approve", "sneaky")
    with pytest.raises(DomainError):
        workflow.act(step, user("linemanager"), "bogus", "x")


def test_return_then_resubmit_restarts_at_level_one(app):
    from app.services import requisitions
    req = make_requisition(user("employee"))
    inst = workflow.latest_instance("requisition", req.id)
    workflow.act(inst.current_step, user("linemanager"), "approve", "fine")
    workflow.act(inst.current_step, user("finance"), "return", "Please clarify the justification")
    assert req.status == "Returned" and inst.status == "Returned"
    assert all(s.status in ("Approved", "Returned", "Cancelled") for s in inst.steps)
    note = Notification.query.filter_by(user_id=user("employee").id).order_by(Notification.id.desc()).first()
    assert "returned for revision" in note.body
    requisitions.submit(req, user("employee"))
    new = workflow.latest_instance("requisition", req.id)
    assert new.round == 2 and new.current_step.level == 1
    assert req.version == 2 and len(req.versions) == 2


def test_reject_is_final(app):
    from app.services import requisitions
    req = make_requisition(user("employee"))
    workflow.act(workflow.latest_instance("requisition", req.id).current_step, user("linemanager"), "reject", "No")
    assert req.status == "Rejected"
    with pytest.raises(DomainError):
        requisitions.submit(req, user("employee"))


def test_delegation_routes_to_delegate(app):
    db.session.add(Delegation(user_id=user("linemanager").id, delegate_id=user("hrbp").id,
                              start_date=today() - timedelta(days=1), end_date=today() + timedelta(days=5)))
    db.session.flush()
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    assert step.approver.username == "linemanager" and step.assignee.username == "hrbp"
    workflow.act(step, user("hrbp"), "approve", "On behalf of Mandla")
    assert step.actor.username == "hrbp" and step.approver.username == "linemanager"


def test_expired_delegation_is_ignored(app):
    db.session.add(Delegation(user_id=user("linemanager").id, delegate_id=user("hrbp").id,
                              start_date=today() - timedelta(days=10), end_date=today() - timedelta(days=1)))
    req = make_requisition(user("employee"))
    assert workflow.latest_instance("requisition", req.id).current_step.assignee.username == "linemanager"


def test_approver_on_leave_without_delegate_goes_to_manager(app):
    db.session.add(LeaveEntry(employee_id=user("linemanager").employee_id, start_date=today(),
                              end_date=today() + timedelta(days=3)))
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    assert step.assignee.username == "hod" and "on leave" in step.routing_note


def test_delegation_route_via_ui_reroutes_waiting_steps(client, app):
    from tests.conftest import login
    req = make_requisition(user("employee"))
    db.session.commit()
    login(client, "linemanager")
    r = client.post("/approvals/delegations", data={"delegate_id": user("hrbp").id,
                                                    "start_date": today().isoformat(),
                                                    "end_date": (today() + timedelta(days=3)).isoformat()})
    assert r.status_code == 302
    step = workflow.latest_instance("requisition", req.id).current_step
    assert step.assignee.username == "hrbp"


def test_sla_due_date_skips_public_holiday(app):
    # Activated Thu 24 Dec 2026 10:00 with a 2-day SLA: 25, 26 holidays, 27 Sunday, 28 Mon, 29 Tue.
    from app.services.calendar import add_business_days
    assert add_business_days(datetime(2026, 12, 24, 10), 2) == datetime(2026, 12, 29, 10)


def test_sla_reminder_then_escalation(app):
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    step.activated_at = datetime(2026, 11, 2, 9, 0)          # Monday
    step.due_at = datetime(2026, 11, 4, 9, 0)                 # 2 business days
    db.session.flush()
    assert workflow.run_sla_checks(datetime(2026, 11, 2, 20, 0)) == {"reminded": 0, "escalated": 0}
    assert workflow.run_sla_checks(datetime(2026, 11, 3, 10, 0)) == {"reminded": 1, "escalated": 0}
    assert workflow.run_sla_checks(datetime(2026, 11, 3, 12, 0)) == {"reminded": 0, "escalated": 0}
    result = workflow.run_sla_checks(datetime(2026, 11, 4, 9, 30))
    assert result == {"reminded": 0, "escalated": 1}
    assert step.assignee.username == "hod" and step.escalated_from.username == "linemanager"
    # The original approver keeps the right to act; so does the escalation target.
    workflow.act(step, user("hod"), "approve", "Escalated and approved")
    assert step.status == "Approved"


def test_reminder_counts_business_hours_over_weekend(app):
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    step.activated_at = datetime(2026, 10, 30, 16, 0)        # Friday afternoon
    step.due_at = datetime(2026, 11, 3, 16, 0)
    db.session.flush()
    assert workflow.run_sla_checks(datetime(2026, 11, 1, 23, 0))["reminded"] == 0   # Sunday night: only 8 hours
    assert workflow.run_sla_checks(datetime(2026, 11, 2, 17, 0))["reminded"] == 1   # Monday 17:00: 25 hours


def test_inbox_and_act_route(client):
    from tests.conftest import login
    req = make_requisition(user("employee"))
    db.session.commit()
    login(client, "linemanager")
    page = client.get("/approvals/")
    assert req.reference.encode() in page.data
    step = workflow.latest_instance("requisition", req.id).current_step
    r = client.post(f"/approvals/steps/{step.id}/act", data={"action": "approve", "comment": ""})
    assert r.status_code == 302
    assert db.session.get(WorkflowStep, step.id).status == "Pending"     # comment missing
    client.post(f"/approvals/steps/{step.id}/act", data={"action": "approve", "comment": "Good"})
    assert db.session.get(WorkflowStep, step.id).status == "Approved"
    from app.models import AuditLog
    assert AuditLog.query.filter_by(action="approval.approve").count() == 1


def test_routing_rule_edit_validates_condition(client):
    from app.models import RoutingRule
    from tests.conftest import login
    login(client, "hradmin")
    rule = RoutingRule.query.filter_by(level=4).first()
    r = client.post(f"/admin/rules/{rule.id}", data={"workflow_type": "requisition", "level": 4, "name": "HR Manager",
                                                   "approver": "HR Manager", "condition": "grade >= ", "sla_days": 3,
                                                   "active": "1"}, follow_redirects=True)
    assert b"Condition isn" in r.data
    client.post(f"/admin/rules/{rule.id}", data={"workflow_type": "requisition", "level": 4, "name": "HR Manager",
                                               "approver": "HR Manager", "condition": "grade >= 6", "sla_days": 3,
                                               "active": "1"})
    assert db.session.get(RoutingRule, rule.id).condition == "grade >= 6"
