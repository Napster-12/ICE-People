"""Phase 3: approval routing, no self-approval, delegation, return/resubmit, SLA reminders and escalation."""
import itertools
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import BudgetLine, Delegation, Department, JobGrade, LeaveEntry, Notification, WorkflowStep
from app.services import workflow
from app.services.dates import now, today
from app.services.errors import DomainError
from tests.conftest import make_requisition, user


def chain_names(req):
    inst = workflow.latest_instance("requisition", req.id)
    return [s.name for s in inst.steps]


CHAIN = ["Line manager", "Finance", "Group HR Manager", "GCOO / Exco"]


@pytest.mark.parametrize("new,over,grade,executive", list(itertools.product([False, True], [False, True],
                                                                             [2, 4], [False, True])))
def test_every_requisition_follows_the_same_chain(app, new, over, grade, executive):
    """Decided 31 Oct 2026: Department Manager → Line Manager → Finance → Group HR → GCOO / Exco; a Department
    Manager raising it skips their own step."""
    if over:
        for line in BudgetLine.query.all():
            line.amount = Decimal("1000")
    fields = {"job_grade_id": JobGrade.query.filter_by(grade=grade).first().id, "is_executive": executive}
    if new:
        fields.update(headcount_type="New", replaced_employee_id=None)
    req = make_requisition(user("hod"), **fields)   # a Department Manager may set the executive flag
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
    assert inst.current_step.assignee.username == "linemanager"   # above the Sales Department Manager
    for actor in ("linemanager", "finance", "grouphr"):
        workflow.act(inst.current_step, user(actor), "approve", "ok")
    assert inst.current_step.assignee.username == "exco"


def test_line_manager_step_goes_to_the_line_manager_above_the_department_manager(app):
    req = make_requisition(user("hod"))                     # Sales Department Manager raises it
    step = workflow.latest_instance("requisition", req.id).current_step
    assert step.name == "Line manager" and step.assignee.username == "linemanager"
    fin = Department.query.filter_by(code="FIN").first()     # Finance's Department Manager reports to the GCOO
    req2 = make_requisition(user("otherhod"), department_id=fin.id, cost_centre_id=fin.cost_centres[0].id)
    assert workflow.latest_instance("requisition", req2.id).current_step.assignee.username == "gcoo"


def test_no_self_approval_routes_to_originators_manager(app):
    # Finance raises a requisition: level 2 would be Finance themselves.
    req = make_requisition(user("finance"))
    inst = workflow.latest_instance("requisition", req.id)
    workflow.act(inst.current_step, user("linemanager"), "approve", "OK from line manager")
    step2 = inst.current_step
    assert step2.name == "Finance"
    assert step2.assignee.username == "gcoo"               # Finance's manager
    assert "can't approve their own" in step2.routing_note
    with pytest.raises(DomainError):
        workflow.act(step2, user("finance"), "approve", "self")


def test_full_approval_commits_budget(app):
    req = make_requisition(user("hod"), headcount_type="New", replaced_employee_id=None)
    inst = workflow.latest_instance("requisition", req.id)
    for actor in ("linemanager", "finance", "grouphr", "gcoo"):
        workflow.act(inst.current_step, user(actor), "approve", f"Approved by {actor}")
    assert inst.status == "Approved" and req.status == "Approved"
    assert req.approved_position.status == "In recruitment"
    assert Decimal(req.committed_amount) == Decimal(req.ctc)
    assert Decimal(req.budget_line.committed) == Decimal(req.ctc)


def test_reason_needed_to_return_or_reject_and_only_assignee_can_act(app):
    req = make_requisition(user("employee"))
    step = workflow.latest_instance("requisition", req.id).current_step
    for action in ("return", "reject"):
        with pytest.raises(DomainError, match="Give a reason"):
            workflow.act(step, user("linemanager"), action, "  ")
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
    assert new.round == 2 and new.current_step == new.steps[0]
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
    assert step.assignee.username == "gcoo" and "on leave" in step.routing_note   # the line manager's manager


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
    assert step.assignee.username == "gcoo" and step.escalated_from.username == "linemanager"
    # The original approver keeps the right to act; so does the escalation target.
    workflow.act(step, user("gcoo"), "approve", "Escalated and approved")
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
    assert b'data-act-open="reject"' in client.get(f"/requisitions/{req.id}").data   # buttons; the box opens on demand
    for action in ("return", "reject"):                                  # a reason is required for these two
        r = client.post(f"/approvals/steps/{step.id}/act", data={"action": action, "comment": " "})
        assert r.status_code == 302 and db.session.get(WorkflowStep, step.id).status == "Pending"
    client.post(f"/approvals/steps/{step.id}/act", data={"action": "approve"})   # approving needs no comment
    approved = db.session.get(WorkflowStep, step.id)
    assert approved.status == "Approved" and approved.comment is None
    assert client.get("/approvals/").status_code == 200                  # "decided" list with no comment
    from app.models import AuditLog
    assert AuditLog.query.filter_by(action="approval.approve").count() == 1


def test_routing_rule_edit_validates_condition(client):
    from app.models import RoutingRule
    from tests.conftest import login
    login(client, "it")
    rule = RoutingRule.query.filter_by(level=4).first()
    r = client.post(f"/admin/rules/{rule.id}", data={"workflow_type": "requisition", "level": 4, "name": "HR Manager",
                                                   "approver": "HR Manager", "condition": "grade >= ", "sla_days": 3,
                                                   "active": "1"}, follow_redirects=True)
    assert b"Condition isn" in r.data
    client.post(f"/admin/rules/{rule.id}", data={"workflow_type": "requisition", "level": 4, "name": "HR Manager",
                                               "approver": "HR Manager", "condition": "grade >= 6", "sla_days": 3,
                                               "active": "1"})
    assert db.session.get(RoutingRule, rule.id).condition == "grade >= 6"


def test_requisition_raised_by_hr_goes_to_the_department_manager_first(app):
    """Decided 31 Oct 2026: HR's requisition starts with the position's Department Manager, not HR's own manager."""
    req = make_requisition(user("hrbp"))                                   # a Sales position
    inst = workflow.latest_instance("requisition", req.id)
    assert [s.name for s in inst.steps] == ["Department manager", "Line manager", "Finance", "Group HR Manager",
                                            "GCOO / Exco"]
    assert inst.current_step.approver_id == user("hod").id                # head of Sales
    workflow.act(inst.current_step, user("hod"), "approve", None)
    assert inst.current_step.assignee.username == "linemanager"           # the line manager above them
    by_manager = make_requisition(user("hod"))
    assert workflow.latest_instance("requisition", by_manager.id).steps[0].name == "Line manager"


def test_step_with_no_approver_falls_back_to_originators_manager_when_hr_admin_raised_it(app):
    from app.services.workflow import resolve_approver
    user("grouphr").active = False                              # nobody holds Group HR Manager
    db.session.flush()
    who, note = resolve_approver("Group HR Manager", user("hradmin"), None)
    assert who.username == "hrmanager" and "originator's manager" in note   # HR Admin raised it: their manager
