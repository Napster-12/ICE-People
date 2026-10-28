"""Seed demo data (idempotent: safe to run again).

    flask db upgrade
    python seed.py

Creates business units, regions, branches and job families, departments and cost
centres, grades 1–12 with salary bands, FY2026/27 budgets (one cost centre near its
limit), the approved positions register (one position per seat, with reporting lines,
filled by the test users), SA public holidays for 2026–2027, one test user per role,
five sample requisitions and one ad-hoc position request waiting at Finance.
Every test user's password is SEED_PASSWORD from .env.
"""
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import inspect

from app import create_app
from app.extensions import db

USERS = [
    # username, first, last, roles, department, cost centre, position, grade, manager username
    ("gcoo", "Nomvula", "Mkhize", ["GCOO"], "OPS", "OPS-100", "Group Chief Operating Officer", 12, None),
    ("grouphr", "Thandiwe", "Dlamini", ["Group HR Manager"], "HR", "HR-100", "Group HR Manager", 11, "gcoo"),
    ("hrmanager", "Sipho", "Ndlovu", ["HR Manager"], "HR", "HR-100", "HR Manager", 10, "grouphr"),
    ("hrbp", "Lerato", "Mokoena", ["HR Business Partner"], "HR", "HR-100", "HR Business Partner", 8, "hrmanager"),
    ("recruiter", "Ayanda", "Zulu", ["Recruiter"], "HR", "HR-200", "Talent Acquisition Specialist", 7, "hrmanager"),
    ("hrod", "Zanele", "Khumalo", ["HR OD"], "HR", "HR-200", "Organisational Development Specialist", 8, "hrmanager"),
    ("hradmin", "Bongani", "Cele", ["HR Admin"], "HR", "HR-100", "HR Systems Administrator", 6, "hrmanager"),
    ("hod", "Precious", "Naidoo", ["HOD"], "SAL", "SAL-100", "Head of Sales", 10, "gcoo"),
    ("linemanager", "Mandla", "Shabalala", ["Line Manager"], "SAL", "SAL-100", "Sales Team Leader", 7, "hod"),
    ("employee", "Nokuthula", "Buthelezi", [], "SAL", "SAL-100", "Funeral Policy Sales Consultant", 4, "linemanager"),
    ("panel", "Zinhle", "Maseko", ["Panel Member"], "SAL", "SAL-200", "Senior Sales Consultant", 5, "linemanager"),
    ("finance", "Kagiso", "Molefe", ["Finance / Budget Controller"], "FIN", "FIN-100", "Budget Controller", 9, "gcoo"),
    ("payroll", "Lindiwe", "Pillay", ["Payroll"], "FIN", "FIN-100", "Payroll Officer", 6, "finance"),
    ("it", "Sibusiso", "Govender", ["IT"], "OPS", "OPS-200", "IT Support Lead", 7, "gcoo"),
    ("assets", "Naledi", "Botha", ["Asset Controller"], "OPS", "OPS-100", "Asset Controller", 6, "gcoo"),
    ("compliance", "Thabo", "Mahlangu", ["Compliance"], "OPS", "OPS-100", "Compliance Officer", 8, "gcoo"),
    ("exco", "Sibongile", "Ntuli", ["Exco"], "OPS", "OPS-100", "Executive: Strategy", 12, None),
]

DEPARTMENTS = [
    ("HR", "Human Resources", [("HR-100", "HR Operations"), ("HR-200", "Talent and Development")], "grouphr"),
    ("FIN", "Finance", [("FIN-100", "Finance and Payroll")], "finance"),
    ("SAL", "Sales", [("SAL-100", "Sales KwaZulu-Natal"), ("SAL-200", "Sales Gauteng")], "hod"),
    ("OPS", "Operations", [("OPS-100", "Group Operations"), ("OPS-200", "Information Technology")], "gcoo"),
]

# cost centre: (budget amount, already consumed). SAL-200 is close to its limit.
BUDGETS = {"HR-100": ("6500000", "3900000"), "HR-200": ("2800000", "1400000"), "FIN-100": ("4200000", "2600000"),
           "SAL-100": ("9800000", "5200000"), "SAL-200": ("2400000", "2150000"),
           "OPS-100": ("7800000", "5100000"), "OPS-200": ("3600000", "2300000")}

BUSINESS_UNITS = [("SALES", "Sales", ["SAL"]), ("CORP", "Corporate Services", ["HR", "FIN"]),
                  ("OPS", "Operations", ["OPS"])]
REGIONS = [("KZN", "KwaZulu-Natal"), ("GP", "Gauteng")]
BRANCHES = [("HO", "Head office", "KZN"), ("DBN", "Durban", "KZN"), ("PTN", "Pinetown", "KZN"),
            ("JHB", "Johannesburg", "GP")]
JOB_FAMILIES = [("SALES", "Sales"), ("HRM", "Human resources"), ("FINC", "Finance"), ("ICT", "ICT"),
                ("MGMT", "Management"), ("OPS", "Operations")]
FAMILY_FOR_DEPT = {"SAL": "SALES", "HR": "HRM", "FIN": "FINC", "OPS": "OPS"}

# Vacant positions on the register: department, cost centre, title, grade, seats, branch, family,
# reports to (username of the manager whose position it reports to), days vacant, minimum requirements.
VACANT_POSITIONS = [
    ("SAL", "SAL-100", "Funeral Policy Sales Consultant", 4, 4, "DBN", "SALES", "linemanager", 18,
     "Matric\n1 year of sales experience\nValid driver's licence"),
    ("SAL", "SAL-200", "Regional Sales Manager", 7, 1, "JHB", "MGMT", "hod", 74,
     "Bachelor's degree or diploma in sales or marketing\n5 years' sales management experience"),
    ("SAL", "SAL-100", "Head of Digital Sales", 9, 1, "HO", "MGMT", "hod", 41,
     "Bachelor's degree (NQF 7)\n8 years' experience, 3 in digital sales"),
    ("SAL", "SAL-100", "Sales Data Analyst", 6, 1, "HO", "SALES", "linemanager", 38,
     "Bachelor's degree (NQF 7) in Statistics, Mathematics or Information Systems\nSQL and Power BI"),
    ("SAL", "SAL-100", "Branch Administrator", 5, 1, "PTN", "SALES", "linemanager", 52, "Matric\nMS Office"),
    ("HR", "HR-200", "Talent Acquisition Specialist", 7, 1, "HO", "HRM", "hrmanager", 12,
     "Diploma in HR\n3 years' recruitment experience"),
    ("FIN", "FIN-100", "Payroll Officer", 6, 1, "HO", "FINC", "finance", 26,
     "Diploma in payroll or finance\nSage 300 People experience"),
    ("OPS", "OPS-200", "IT Support Technician", 5, 2, "HO", "ICT", "it", 96, "A+ / N+ certification\nDriver's licence"),
]


def main():
    app = create_app()
    app.config["MOCK_EMAIL_ECHO"] = False
    password = os.environ.get("SEED_PASSWORD")
    if not password:
        sys.exit("Set SEED_PASSWORD in .env first (see .env.example).")
    with app.app_context():
        if not inspect(db.engine).has_table("users"):
            sys.exit("The database has no tables yet. Run `flask db upgrade` first.")
        from app.models import (ApprovedPosition, Asset, BudgetLine, CostCentre, Department, Employee, JobGrade,
                                LeaveEntry, Requisition, Role, User)
        from app.services import budget, requisitions
        from app.services.dates import today
        from app.services.reference_data import seed_reference_data

        seed_reference_data()
        fy = budget.financial_year_for(today())

        for code, name, centres, _hod in DEPARTMENTS:
            dept = Department.query.filter_by(code=code).first() or Department(code=code, name=name)
            db.session.add(dept)
            db.session.flush()
            for cc_code, cc_name in centres:
                if not CostCentre.query.filter_by(code=cc_code).first():
                    db.session.add(CostCentre(code=cc_code, name=cc_name, department_id=dept.id))
        db.session.flush()
        depts = {d.code: d for d in Department.query.all()}
        centres = {c.code: c for c in CostCentre.query.all()}
        grades = {g.grade: g for g in JobGrade.query.all()}

        for cc_code, (amount, consumed) in BUDGETS.items():
            if not budget.get_line(centres[cc_code].id, fy):
                db.session.add(BudgetLine(cost_centre_id=centres[cc_code].id, financial_year=fy,
                                          amount=Decimal(amount), committed=0, consumed=Decimal(consumed)))

        roles = {r.name: r for r in Role.query.all()}
        users = {}
        for n, (username, first, last, role_names, d_code, cc_code, position, grade, _mgr) in enumerate(USERS, 1):
            emp = Employee.query.filter_by(employee_number=f"ICE{1000 + n}").first()
            if emp is None:
                emp = Employee(employee_number=f"ICE{1000 + n}", first_name=first, last_name=last,
                               email=f"{username}@icebolethu.test", department_id=depts[d_code].id,
                               cost_centre_id=centres[cc_code].id, job_grade_id=grades[grade].id,
                               position_title=position, start_date=date(2019, 1, 1) + timedelta(days=97 * n),
                               employment_type="Permanent", status="Permanent")
                db.session.add(emp)
                db.session.flush()
            user = User.query.filter_by(username=username).first()
            if user is None:
                user = User(username=username, full_name=f"{first} {last}", email=emp.email, employee_id=emp.id,
                            password_hash="")
                user.set_password(password)
                user.roles = [roles["Employee"]] + [roles[r] for r in role_names]
                db.session.add(user)
            users[username] = user
        db.session.flush()
        for username, *_rest, manager in USERS:
            if manager and users[username].employee.manager_id is None:
                users[username].employee.manager_id = users[manager].employee.id
        for code, _name, _centres, hod in DEPARTMENTS:
            depts[code].hod_employee_id = depts[code].hod_employee_id or users[hod].employee.id
        seed_org_structure(depts)
        if not ApprovedPosition.query.first():
            seed_positions(users, depts, centres, grades, fy)

        emp = users["employee"].employee
        if not emp.assets:
            db.session.add_all([
                Asset(employee_id=emp.id, asset_tag="LT-0451", category="Laptop", description="Dell Latitude 5440",
                      issued_on=date(2024, 2, 1)),
                Asset(employee_id=emp.id, asset_tag="PH-0219", category="Phone", description="Samsung Galaxy A35",
                      issued_on=date(2024, 2, 1)),
                Asset(employee_id=emp.id, asset_tag="AC-1180", category="Access card", description="Head office access",
                      issued_on=date(2024, 2, 1))])
        if not LeaveEntry.query.first():
            db.session.add(LeaveEntry(employee_id=users["hrbp"].employee.id, start_date=today() + timedelta(days=40),
                                      end_date=today() + timedelta(days=50), leave_type="Annual"))
        db.session.commit()

        if Requisition.query.count() == 0:
            seed_requisitions(users, requisitions)
        db.session.commit()

        print(f"Seed complete for {budget.fy_label(fy)}.")
        print(f"Test users (password = SEED_PASSWORD from .env): {', '.join(u[0] for u in USERS)}")
        print("To bring in the original portal's jobs, CVs and applications: flask import-legacy")


def seed_org_structure(depts):
    from app.models import Branch, BusinessUnit, JobFamily, Region
    for code, name, dept_codes in BUSINESS_UNITS:
        bu = BusinessUnit.query.filter_by(code=code).first() or BusinessUnit(code=code, name=name)
        db.session.add(bu)
        db.session.flush()
        for d in dept_codes:
            depts[d].business_unit_id = depts[d].business_unit_id or bu.id
    for code, name in REGIONS:
        if not Region.query.filter_by(code=code).first():
            db.session.add(Region(code=code, name=name))
    db.session.flush()
    for code, name, region in BRANCHES:
        if not Branch.query.filter_by(code=code).first():
            db.session.add(Branch(code=code, name=name, region_id=Region.query.filter_by(code=region).first().id))
    for code, name in JOB_FAMILIES:
        if not JobFamily.query.filter_by(code=code).first():
            db.session.add(JobFamily(code=code, name=name))
    db.session.flush()


def seed_positions(users, depts, centres, grades, fy):
    """The approved register: a filled position for every test user (reporting to their manager's position),
    plus vacant and frozen seats. The register is approved."""
    from app.models import ApprovedPosition, Branch, JobFamily, PositionRegister
    from app.services.dates import today
    from app.services.refs import next_reference
    branches = {b.code: b for b in Branch.query.all()}
    families = {f.code: f for f in JobFamily.query.all()}
    grade_ctc = {g: (grades[g].band_min + grades[g].band_max) / 2 for g in grades}

    def add(d_code, cc_code, title, grade, branch, family, reports_to=None, **extra):
        p = ApprovedPosition(position_number=next_reference("POS"), title=title, department_id=depts[d_code].id,
                             cost_centre_id=centres[cc_code].id, job_grade_id=grades[grade].id,
                             branch_id=branches[branch].id, job_family_id=families[family].id,
                             budgeted_ctc=grade_ctc[grade], financial_year=fy,
                             reports_to_id=reports_to.id if reports_to else None, **extra)
        db.session.add(p)
        db.session.flush()
        return p

    held = {}
    for username, _f, _l, _roles, d_code, cc_code, title, grade, manager in USERS:   # managers come first
        branch = "DBN" if d_code == "SAL" and username in ("linemanager", "employee", "panel") else "HO"
        family = "MGMT" if grade >= 9 else FAMILY_FOR_DEPT[d_code]
        held[username] = add(d_code, cc_code, title, grade, branch, family, held.get(manager), status="Filled",
                             filled_on=date(2024, 1, 15))
        users[username].employee.approved_position_id = held[username].id
    for d_code, cc_code, title, grade, seats, branch, family, manager, days, reqs in VACANT_POSITIONS:
        for _ in range(seats):
            add(d_code, cc_code, title, grade, branch, family, held[manager], status="Vacant",
                vacant_since=today() - timedelta(days=days), minimum_requirements=reqs)
    # One consultant seat was left by a leaver (a replacement); one administrator seat is frozen.
    consultant = ApprovedPosition.query.filter_by(title="Funeral Policy Sales Consultant", status="Vacant").first()
    consultant.last_holder_id = users["panel"].employee.id
    ApprovedPosition.query.filter_by(title="Branch Administrator").first().status = "Frozen"
    db.session.add(PositionRegister(financial_year=fy, status="Approved", approved_at=datetime.now()))
    db.session.flush()


def seed_requisitions(users, requisitions):
    from app.models import ApprovedPosition, Requisition
    from app.services import positions, workflow
    from app.services.dates import today
    start = today() + timedelta(days=45)
    justification = ("{} The team cannot meet its targets for the coming quarter without this role, "
                     "and the workload is currently spread across existing staff.")

    def vacant(title, replacement=False):
        q = ApprovedPosition.query.filter_by(title=title, status="Vacant")
        q = q.filter(ApprovedPosition.last_holder_id.isnot(None) if replacement else ApprovedPosition.last_holder_id.is_(None))
        busy = [r.approved_position_id for r in Requisition.query.all()]
        return next(p for p in q.order_by(ApprovedPosition.id) if p.id not in busy)

    def make(originator, position, submit=True, **fields):
        req = Requisition()
        requisitions.apply_form(req, dict(fields, approved_position_id=position.id), originator)
        requisitions.save(req, originator)
        if submit:
            requisitions.submit(req, originator)
        db.session.flush()
        return req

    lm, hod = users["linemanager"], users["hod"]
    make(lm, vacant("Funeral Policy Sales Consultant"), submit=False, employment_type="Permanent",
         required_start_date=start, justification="Draft: second consultant for the Pietermaritzburg branch.")
    make(lm, vacant("Funeral Policy Sales Consultant", replacement=True), employment_type="Permanent",
         required_start_date=start,
         justification=justification.format("Replacement for a consultant moving to the Gauteng team."))
    make(hod, vacant("Regional Sales Manager"), employment_type="Permanent", required_start_date=start,
         justification=justification.format("Gauteng needs a regional manager to open two new branches."))
    make(lm, vacant("Sales Data Analyst"), employment_type="Contract", required_start_date=start,
         contract_end_date=start + timedelta(days=364),
         justification=justification.format("Twelve-month contract to build sales and lapse-rate reporting."))
    make(hod, vacant("Head of Digital Sales"), employment_type="Permanent", is_executive=True,
         required_start_date=start + timedelta(days=30),
         justification=justification.format("Strategic role to launch online funeral policy sales."))

    # An ad-hoc position the line manager needs, approved by the HOD and now waiting at Finance.
    sal = ApprovedPosition.query.filter_by(title="Sales Team Leader").first()
    inst = positions.request_ad_hoc({
        "title": "Claims Liaison Officer", "department_id": sal.department_id, "cost_centre_id": sal.cost_centre_id,
        "job_grade_id": ApprovedPosition.query.filter_by(title="Branch Administrator").first().job_grade_id,
        "branch_id": sal.branch_id, "reports_to_id": sal.id, "budgeted_ctc": None,
        "minimum_requirements": "Matric\n2 years' funeral claims experience",
        "justification": "Claims queries from the Durban branch now take a consultant away from sales for about "
                         "two days a week. A dedicated liaison officer would handle them."}, lm)
    workflow.act(inst.current_step, hod, "approve", "Agreed: the branch needs this role.")


if __name__ == "__main__":
    main()
