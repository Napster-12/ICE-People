"""Portal homes on /dashboard, one per portal (infographic pp. 8, 10, 11)."""
from app.dashboards.routes import _due_label
from app.services.dates import now
from datetime import timedelta
from tests.conftest import login, make_requisition, user


def test_admin_home_shows_figures_and_module_tiles(client):
    login(client, "hradmin")
    page = client.get("/dashboard").data
    assert b"Requisitions awaiting approval" in page and b"Talent acquisition" in page
    assert b"Approved positions" in page and b"Open settings" not in page   # settings belong to ICT
    assert b"Coming soon" in page            # modules not built yet


def test_ict_home_has_settings_and_reports(client):
    login(client, "it")
    page = client.get("/dashboard").data
    assert b"Open settings" in page and b"Items overdue" in page


def test_finance_home_has_budget_but_no_hr_tiles(client):
    login(client, "finance")
    page = client.get("/dashboard").data
    assert b"Headcount budget" in page and b"Org &amp; reporting tree" not in page and b"Open settings" not in page


def test_manager_home_lists_tasks(client, app):
    req = make_requisition(user("hod"))
    req.status = "Returned"
    from app.extensions import db
    db.session.commit()
    login(client, "hod")                                          # Department Manager: raises requisitions
    page = client.get("/dashboard").data
    assert b"My tasks" in page and b"My team at a glance" in page and b"Raise a requisition" in page
    assert f"Fix and resubmit: {req.reference}".encode() in page


def test_line_manager_home_has_no_raise_tile(client):
    login(client, "linemanager")                                  # Line Managers approve, they don't raise
    page = client.get("/dashboard").data
    assert b"Raise a requisition" not in page and b"Team requisitions" in page


def test_staff_home(client):
    login(client, "employee")
    page = client.get("/dashboard").data
    assert b"My profile" in page and b"Leave and payslips" in page and b"Raise a requisition" not in page


def test_due_labels(app):
    assert _due_label(None)[0] == "Open"
    assert _due_label(now() - timedelta(days=1))[0] == "Overdue"
    assert _due_label(now())[0] == "Due today"
    assert _due_label(now() + timedelta(days=2))[0] == "2 days"
    assert _due_label(now() + timedelta(days=6))[0] == "This week"
