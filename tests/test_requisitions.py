"""Phase 2 (updated Phase 4): requisition validation, raised from a vacant approved position, statuses, scoping,
routes and audit."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import AuditLog, Department, JobGrade, Requisition, StoredFile
from app.services import requisitions
from app.services.dates import today
from app.services.errors import DomainError
from app.services.requisitions import FLOW, ValidationFailed
from tests.conftest import login, make_position, make_requisition, user


def test_draft_needs_a_position_and_takes_its_details(app):
    req = Requisition()
    with pytest.raises(ValidationFailed, match="vacant approved position"):
        requisitions.save(req, user("linemanager"))
    position = make_position(title="Clerk")
    requisitions.apply_form(req, {"approved_position_id": position.id, "title": "Something else"}, user("linemanager"))
    requisitions.save(req, user("linemanager"))
    assert req.reference.startswith("REQ-") and req.status == "Draft"
    assert req.title == "Clerk" and req.department_id == position.department_id
    assert req.headcount_type == "New"
    assert AuditLog.query.filter_by(entity="requisition", action="create").count() == 1


def test_position_someone_left_is_a_replacement(app):
    leaver = user("employee").employee
    req = make_requisition(user("linemanager"), headcount_type="Replacement", replaced_employee_id=leaver.id)
    assert req.headcount_type == "Replacement" and req.replaced_employee_id == leaver.id


@pytest.mark.parametrize("overrides,message", [
    ({"justification": "Too short"}, "at least 50 characters"),
    ({"required_start_date": today()}, "must be in the future"),
    ({"employment_type": "Contract"}, "contract end date"),
    ({"job_grade_id": None}, "Choose a job grade"),
])
def test_submit_needs_full_validation(app, overrides, message):
    with pytest.raises(ValidationFailed) as exc:
        make_requisition(user("linemanager"), **overrides)
    assert any(message in e for e in exc.value.errors)


def test_cost_centre_must_belong_to_department(app):
    fin = Department.query.filter_by(code="FIN").first()
    with pytest.raises(ValidationFailed, match="belong"):
        make_requisition(user("linemanager"), cost_centre_id=fin.cost_centres[0].id)


def test_contract_end_after_start(app):
    with pytest.raises(ValidationFailed, match="after the start"):
        make_requisition(user("linemanager"), employment_type="Contract",
                         contract_end_date=today() + timedelta(days=10))


@pytest.mark.parametrize("status", ["Planned", "Pending approval", "In recruitment", "Filled", "Frozen", "Abolished"])
def test_only_a_vacant_position_can_be_requisitioned(app, status):
    position = make_position(status=status)
    with pytest.raises(ValidationFailed, match="not vacant"):
        make_requisition(user("linemanager"), approved_position_id=position.id)


def test_one_open_requisition_per_position(app):
    first = make_requisition(user("linemanager"))
    second = make_requisition(user("hod"), submit=False, approved_position_id=first.approved_position_id)
    with pytest.raises(ValidationFailed, match="already has an open requisition"):
        requisitions.submit(second, user("hod"))
    requisitions.cancel(first, user("linemanager"))
    requisitions.submit(second, user("hod"))
    assert second.status == "In Approval"


def test_executive_flag_only_set_by_hod_and_above(app):
    lm_req = make_requisition(user("linemanager"), is_executive=True)
    assert lm_req.is_executive is False
    hod_req = make_requisition(user("hod"), is_executive=True)
    assert hod_req.is_executive is True


def test_status_machine_rejects_invalid_transition():
    assert FLOW.can("Draft", "Submitted")
    with pytest.raises(DomainError):
        FLOW.check("Draft", "Approved")
    with pytest.raises(DomainError):
        FLOW.check("Filled", "Cancelled")


def test_cancel_by_originator_only_before_approval(app):
    req = make_requisition(user("employee"))
    with pytest.raises(DomainError, match="Only the originator"):
        requisitions.cancel(req, user("linemanager"))
    requisitions.cancel(req, user("employee"), "No longer needed")
    assert req.status == "Cancelled"
    from app.services import workflow
    assert workflow.latest_instance("requisition", req.id).status == "Cancelled"


def test_only_originator_can_submit(app):
    req = make_requisition(user("linemanager"), submit=False)
    with pytest.raises(DomainError):
        requisitions.submit(req, user("hod"))


def test_scoping(app):
    lm_req = make_requisition(user("linemanager"))
    hr_req = make_requisition(user("hrbp"), department_id=Department.query.filter_by(code="HR").first().id,
                              cost_centre_id=Department.query.filter_by(code="HR").first().cost_centres[0].id)
    assert requisitions.can_view(user("linemanager"), lm_req)
    assert not requisitions.can_view(user("linemanager"), hr_req)
    assert requisitions.can_view(user("hod"), lm_req)           # HOD of Sales: department scope / approver
    assert not requisitions.can_view(user("otherhod"), lm_req)  # HOD of another department
    assert requisitions.can_view(user("finance"), hr_req)       # Finance sees all
    assert requisitions.can_view(user("grouphr"), hr_req)       # approver of the HRBP's request


def test_routes_new_draft_submit_and_detail(client):
    login(client, "linemanager")
    position = make_position(title="Branch Consultant")
    taken = make_position(title="Not mine", department_id=Department.query.filter_by(code="HR").first().id,
                          cost_centre_id=Department.query.filter_by(code="HR").first().cost_centres[0].id)
    db.session.commit()
    page = client.get("/requisitions/new").data
    assert position.position_number.encode() in page and taken.position_number.encode() not in page
    data = {"approved_position_id": position.id, "employment_type": "Permanent",
            "required_start_date": (today() + timedelta(days=40)).isoformat(),
            "justification": "x" * 60, "action": "draft"}
    r = client.post("/requisitions/new", data=dict(data, approved_position_id=taken.id), follow_redirects=True)
    assert b"isn&#39;t vacant or isn&#39;t one you can raise" in r.data or b"isn't vacant" in r.data
    r = client.post("/requisitions/new", data=data)
    assert r.status_code == 302
    req = Requisition.query.one()
    assert req.status == "Draft" and req.title == "Branch Consultant"
    assert client.get(f"/requisitions/{req.id}").status_code == 200
    assert position.position_number.encode() in client.get(f"/requisitions/{req.id}/edit").data
    data["action"] = "submit"
    data["justification"] = "short"
    r = client.post(f"/requisitions/{req.id}/edit", data=data, follow_redirects=True)
    assert b"at least 50 characters" in r.data
    assert db.session.get(Requisition, req.id).status == "Draft"
    data["justification"] = "We need another consultant for the new branch opening in the first quarter."
    client.post(f"/requisitions/{req.id}/edit", data=data)
    assert db.session.get(Requisition, req.id).status == "In Approval"
    assert client.get("/requisitions/?status=In+Approval").status_code == 200
    assert req.reference.encode() in client.get("/requisitions/?q=REQ").data
    assert client.get(f"/requisitions/new?position={position.id}").status_code == 200


def test_out_of_scope_requisition_is_403(client):
    req = make_requisition(user("hrbp"), department_id=Department.query.filter_by(code="HR").first().id,
                           cost_centre_id=Department.query.filter_by(code="HR").first().cost_centres[0].id)
    db.session.commit()
    login(client, "linemanager")
    assert client.get(f"/requisitions/{req.id}").status_code == 403
    client.post("/logout")
    login(client, "employee")
    assert client.get("/requisitions/").status_code == 403    # plain employees can't raise requisitions


def test_attachment_whitelist_size_and_download_permission(client, app):
    req = make_requisition(user("linemanager"), submit=False)
    db.session.commit()
    login(client, "linemanager")
    import io
    r = client.post(f"/requisitions/{req.id}/attachments",
                    data={"attachments": (io.BytesIO(b"MZ..."), "virus.exe")}, follow_redirects=True)
    assert b"isn&#39;t an allowed file type" in r.data or b"isn't an allowed file type" in r.data
    big = io.BytesIO(b"0" * (app.config["MAX_UPLOAD_BYTES"] + 1))
    r = client.post(f"/requisitions/{req.id}/attachments", data={"attachments": (big, "big.pdf")}, follow_redirects=True)
    assert b"larger than" in r.data
    client.post(f"/requisitions/{req.id}/attachments", data={"attachments": (io.BytesIO(b"%PDF-1.4 hi"), "jd.pdf")})
    f = StoredFile.query.filter_by(entity_type="requisition").one()
    assert f.stored_name != "jd.pdf" and len(f.sha256) == 64
    assert client.get(f"/files/{f.id}").status_code == 200
    client.post("/logout")
    login(client, "otherhod")
    assert client.get(f"/files/{f.id}").status_code == 403
    assert AuditLog.query.filter_by(action="file.download_denied").count() == 1


def test_cost_centre_api(client):
    login(client, "linemanager")
    sal = Department.query.filter_by(code="SAL").first()
    data = client.get(f"/requisitions/api/cost-centres?department_id={sal.id}").get_json()
    assert [d["id"] for d in data] == [c.id for c in sal.cost_centres]
    check = client.get(f"/requisitions/api/budget-check?job_grade_id={JobGrade.query.first().id}"
                       f"&employment_type=Permanent&cost_centre_id={sal.cost_centres[0].id}").get_json()
    assert check["ok"] and check["ctc"].startswith("R ")
