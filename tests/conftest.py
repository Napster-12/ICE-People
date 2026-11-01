"""Shared fixtures: an app on in-memory SQLite with reference data, a small org
and one user per role. Log in with `login(client, "finance")`."""
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import (ApprovedPosition, BudgetLine, CostCentre, Department, Employee, JobGrade, Role, User)
from app.services.dates import today
from app.services.reference_data import seed_reference_data

PASSWORD = "Test-password-123"

# username: (roles, department, manager)
ORG = {
    "gcoo": (["GCOO"], "OPS", None),
    "grouphr": (["Group HR Manager"], "HR", "gcoo"),
    "hrmanager": (["HR Manager"], "HR", "grouphr"),
    "hrbp": (["HR Business Partner"], "HR", "hrmanager"),
    "recruiter": (["Recruiter"], "HR", "hrmanager"),
    "hradmin": (["HR Admin"], "HR", "hrmanager"),
    # Icebolethu's order (31 Oct 2026): employee → Department Manager → Line Manager → Exco/GCOO.
    "linemanager": (["Line Manager"], "SAL", "gcoo"),
    "hod": (["Department Manager"], "SAL", "linemanager"),
    "employee": ([], "SAL", "hod"),
    "finance": (["Finance"], "FIN", "gcoo"),
    "payroll": (["Payroll"], "FIN", "finance"),
    "it": (["IT"], "OPS", "gcoo"),
    "compliance": (["Compliance"], "OPS", "gcoo"),
    "otherhod": (["Department Manager"], "FIN", "gcoo"),
    "exco": (["Exco"], "OPS", None),
}


@pytest.fixture()
def app():
    upload_dir = tempfile.mkdtemp()
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = upload_dir
    app.config["MOCK_EMAIL_ECHO"] = False
    with app.app_context():
        _db.create_all()
        seed_reference_data()
        build_org()
        _db.session.commit()
        yield app
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()
    shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


def build_org():
    depts = {}
    for code, name in [("HR", "Human Resources"), ("SAL", "Sales"), ("FIN", "Finance"), ("OPS", "Operations")]:
        d = Department(code=code, name=name)
        _db.session.add(d)
        _db.session.flush()
        _db.session.add(CostCentre(code=f"{code}-100", name=f"{name} main", department_id=d.id))
        depts[code] = d
    _db.session.flush()
    fy = financial_year()
    for cc in CostCentre.query.all():
        _db.session.add(BudgetLine(cost_centre_id=cc.id, financial_year=fy, amount=Decimal("5000000"),
                                   committed=0, consumed=0))
    roles = {r.name: r for r in Role.query.all()}
    users = {}
    for n, (username, (role_names, dept, _mgr)) in enumerate(ORG.items(), 1):
        emp = Employee(employee_number=f"T{n:03d}", first_name=username.title(), last_name="Tester",
                       department_id=depts[dept].id, cost_centre_id=depts[dept].cost_centres[0].id
                       if depts[dept].cost_centres else None, status="Permanent", position_title=username)
        _db.session.add(emp)
        _db.session.flush()
        user = User(username=username, full_name=f"{username.title()} Tester", email=f"{username}@test.invalid",
                    employee_id=emp.id, password_hash="")
        user.set_password(PASSWORD)
        user.roles = [roles["Employee"]] + [roles[r] for r in role_names]
        _db.session.add(user)
        users[username] = user
    _db.session.flush()
    for username, (_r, _d, mgr) in ORG.items():
        if mgr:
            users[username].employee.manager_id = users[mgr].employee.id
    depts["SAL"].hod_employee_id = users["hod"].employee.id
    depts["HR"].hod_employee_id = users["grouphr"].employee.id
    depts["FIN"].hod_employee_id = users["otherhod"].employee.id
    from app.models import PositionRegister
    _db.session.add(PositionRegister(financial_year=fy, status="Approved"))
    for _ in range(2):
        make_position(title="Sales Consultant")


def financial_year():
    from app.services.budget import financial_year_for
    return financial_year_for(today() + timedelta(days=30), start_month=3)


def user(username):
    return User.query.filter_by(username=username).first()


def login_path(username):
    """The sign-in page for this user."""
    from app.auth.routes import find_user
    found = find_user(username)
    return "/login/sign-in" if found is None or found.landing == "admin" else f"/login/{found.landing}/sign-in"


def login(client, username, password=PASSWORD):
    return client.post(login_path(username), data={"login": username, "password": password}, follow_redirects=False)


def make_position(status="Vacant", **fields):
    """An approved position on the current register (vacant, Junior, Sales by default)."""
    from app.services.refs import next_reference
    sal = Department.query.filter_by(code="SAL").first()
    values = dict(title="Sales Consultant", department_id=sal.id, cost_centre_id=sal.cost_centres[0].id,
                  job_grade_id=JobGrade.query.filter_by(name="Junior").first().id, financial_year=financial_year(),
                  budgeted_ctc=Decimal("250000.00"))
    values.update(fields)
    p = ApprovedPosition(position_number=next_reference("POS"), status=status,
                         vacant_since=today() if status in ("Vacant", "In recruitment", "Frozen") else None, **values)
    _db.session.add(p)
    _db.session.flush()
    return p


def make_requisition(originator, submit=True, **overrides):
    """A complete, valid requisition (permanent, replacement, Junior, Sales), raised from its own new vacant
    position. Position fields (title, department, cost centre, grade) and the headcount type set the position."""
    from app.models import Requisition
    from app.services import requisitions
    position_fields = {k: overrides.pop(k) for k in ("title", "department_id", "cost_centre_id", "job_grade_id")
                       if k in overrides}
    replacement = overrides.pop("headcount_type", "Replacement") == "Replacement"
    replaced = overrides.pop("replaced_employee_id", user("employee").employee_id)
    if "approved_position_id" not in overrides:
        position = make_position(last_holder_id=replaced if replacement else None, **position_fields)
        overrides["approved_position_id"] = position.id
    fields = dict(employment_type="Permanent", required_start_date=today() + timedelta(days=30), is_executive=False,
                  justification="A replacement consultant is needed to keep the branch at full strength this year.")
    fields.update(overrides)
    req = Requisition()
    requisitions.apply_form(req, fields, originator)
    requisitions.save(req, originator)
    if submit:
        requisitions.submit(req, originator)
    _db.session.flush()
    return req
