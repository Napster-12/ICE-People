"""Seed demo data (idempotent: safe to run again).

    flask db upgrade
    python seed.py

Creates business units, regions, branches and job families, departments and cost
centres, grades 1–12 with salary bands, FY2026/27 budgets (one cost centre near its
limit), the approved positions register (one position per seat, with reporting lines,
filled by the test users), SA public holidays for 2026–2027, one test user per role,
five sample requisitions, one ad-hoc position request waiting at Finance, a small JD library and one live
advert with eight applicants at different stages.
Every test user's password is SEED_PASSWORD from .env.

    python seed.py --accounts-only

creates only what the test users need to sign in (reference data, departments, cost centres, the org
structure, the test users and their reporting lines): no budgets, positions, requisitions, adverts or applicants.

    python seed.py --department-accounts

creates the same reference data and departments, but instead of the test users: a Line Manager
(lm.<dept>, reporting to exco) and a Department Manager (dm.<dept>, reporting to the Line Manager) for every department, plus hradmin, finance, exco (GCOO and Exco) and it.
Emails are <username>@icebolethu.co.za.
"""
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import inspect

from app import create_app
from app.extensions import db

USERS = [
    # username, first, last, roles, department, cost centre, position, grade name, manager username
    ("gcoo", "Nomvula", "Mkhize", ["GCOO"], "OPS", "OPS-100", "Group Chief Operating Officer", "Exco", None),
    ("grouphr", "Thandiwe", "Dlamini", ["Group HR Manager"], "HR", "HR-100", "Group HR Manager", "Manager", "gcoo"),
    ("hrmanager", "Sipho", "Ndlovu", ["HR Manager"], "HR", "HR-100", "HR Manager", "Manager", "grouphr"),
    ("hrbp", "Lerato", "Mokoena", ["HR Business Partner"], "HR", "HR-100", "HR Business Partner", "Senior", "hrmanager"),
    ("recruiter", "Ayanda", "Zulu", ["Recruiter"], "HR", "HR-200", "Talent Acquisition Specialist", "Senior", "hrmanager"),
    ("hrod", "Zanele", "Khumalo", ["HR OD"], "HR", "HR-200", "Organisational Development Specialist", "Senior", "hrmanager"),
    ("hradmin", "Bongani", "Cele", ["HR Admin"], "HR", "HR-100", "HR Systems Administrator", "Senior", "hrmanager"),
    ("hod", "Precious", "Naidoo", ["Department Manager"], "SAL", "SAL-100", "Head of Sales", "Manager", "gcoo"),
    ("linemanager", "Mandla", "Shabalala", ["Line Manager"], "SAL", "SAL-100", "Sales Team Leader", "Manager", "hod"),
    ("employee", "Nokuthula", "Buthelezi", [], "SAL", "SAL-100", "Funeral Policy Sales Consultant", "Junior", "linemanager"),
    ("panel", "Zinhle", "Maseko", ["Panel Member"], "SAL", "SAL-200", "Senior Sales Consultant", "Senior", "linemanager"),
    ("finance", "Kagiso", "Molefe", ["Finance"], "FIN", "FIN-100", "Finance Manager", "Manager", "gcoo"),
    ("payroll", "Lindiwe", "Pillay", ["Payroll"], "FIN", "FIN-100", "Payroll Officer", "Senior", "finance"),
    ("it", "Sibusiso", "Govender", ["IT"], "OPS", "OPS-200", "IT Support Lead", "Senior", "gcoo"),
    ("assets", "Naledi", "Botha", ["Asset Controller"], "OPS", "OPS-100", "Asset Controller", "Senior", "gcoo"),
    ("compliance", "Thabo", "Mahlangu", ["Compliance"], "OPS", "OPS-100", "Compliance Officer", "Senior", "gcoo"),
    ("exco", "Sibongile", "Ntuli", ["Exco"], "OPS", "OPS-100", "Executive: Strategy", "Exco", None),
    # One line manager per department.
    ("lm.catering", "Themba", "Mnguni", ["Line Manager"], "CAT", "CAT-100", "Catering Supervisor", "Manager", "gcoo"),
    ("lm.burials", "Nonhlanhla", "Shezi", ["Line Manager"], "BUR", "BUR-100", "Funeral Services Supervisor", "Manager",
     "gcoo"),
    ("lm.ict", "Kgomotso", "Sebola", ["Line Manager"], "ICT", "ICT-100", "ICT Team Leader", "Manager", "gcoo"),
    ("lm.finance", "Rajesh", "Moodley", ["Line Manager"], "FIN", "FIN-100", "Accounts Team Leader", "Manager", "finance"),
    ("lm.facilities", "Phumzile", "Gumede", ["Line Manager"], "FAC", "FAC-100", "Facilities Supervisor", "Manager", "gcoo"),
    ("lm.fleet", "Vusi", "Mabuza", ["Line Manager"], "FLT", "FLT-100", "Fleet Supervisor", "Manager", "gcoo"),
    ("lm.security", "Sandile", "Majola", ["Line Manager"], "SEC", "SEC-100", "Security Supervisor", "Manager", "gcoo"),
    ("lm.marketing", "Palesa", "Radebe", ["Line Manager"], "MKT", "MKT-100", "Marketing Team Leader", "Manager", "gcoo"),
    ("lm.foundations", "Ntokozo", "Biyela", ["Line Manager"], "FND", "FND-100", "Foundation Projects Team Leader", "Manager",
     "gcoo"),
    ("lm.hr", "Busisiwe", "Hlongwane", ["Line Manager"], "HR", "HR-100", "HR Operations Team Leader", "Manager",
     "hrmanager"),
    ("lm.cleaning", "Gugu", "Ndaba", ["Line Manager"], "CLN", "CLN-100", "Cleaning Supervisor", "Manager", "gcoo"),
    ("lm.risk", "Tshepo", "Modise", ["Line Manager"], "RSK", "RSK-100", "Risk and Compliance Team Leader", "Manager", "gcoo"),
    ("lm.itravel", "Lwazi", "Mthethwa", ["Line Manager"], "ITR", "ITR-100", "Travel Operations Team Leader", "Manager",
     "gcoo"),
]

DEPARTMENTS = [
    ("HR", "Human Resources", [("HR-100", "HR Operations"), ("HR-200", "Talent and Development")], "grouphr"),
    ("FIN", "Finance", [("FIN-100", "Finance and Payroll")], "finance"),
    ("SAL", "Sales", [("SAL-100", "Sales KwaZulu-Natal"), ("SAL-200", "Sales Gauteng")], "hod"),
    ("OPS", "Operations", [("OPS-100", "Group Operations"), ("OPS-200", "Information Technology")], "gcoo"),
    # These departments have no Department Manager test user yet, so the GCOO stands in.
    ("CAT", "Catering", [("CAT-100", "Catering")], "gcoo"),
    ("BUR", "Burials", [("BUR-100", "Burials")], "gcoo"),
    ("ICT", "ICT", [("ICT-100", "ICT")], "gcoo"),
    ("FAC", "Facilities", [("FAC-100", "Facilities")], "gcoo"),
    ("FLT", "Fleet", [("FLT-100", "Fleet")], "gcoo"),
    ("SEC", "Security", [("SEC-100", "Security")], "gcoo"),
    ("MKT", "Marketing", [("MKT-100", "Marketing")], "gcoo"),
    ("FND", "Foundations", [("FND-100", "Foundations")], "gcoo"),
    ("CLN", "Cleaning", [("CLN-100", "Cleaning")], "gcoo"),
    ("RSK", "Risk & Compliance", [("RSK-100", "Risk & Compliance")], "gcoo"),
    ("ITR", "iTravel", [("ITR-100", "iTravel")], "gcoo"),
]

# cost centre: (budget amount, already consumed). SAL-200 is close to its limit.
BUDGETS = {"HR-100": ("6500000", "3900000"), "HR-200": ("2800000", "1400000"), "FIN-100": ("4200000", "2600000"),
           "SAL-100": ("9800000", "5200000"), "SAL-200": ("2400000", "2150000"),
           "OPS-100": ("7800000", "5100000"), "OPS-200": ("3600000", "2300000"),
           "CAT-100": ("2200000", "1300000"), "BUR-100": ("5400000", "3200000"), "ICT-100": ("4800000", "2900000"),
           "FAC-100": ("2600000", "1500000"), "FLT-100": ("6100000", "3800000"), "SEC-100": ("3300000", "2000000"),
           "MKT-100": ("3900000", "2100000"), "FND-100": ("1800000", "900000"), "CLN-100": ("1900000", "1150000"),
           "RSK-100": ("2700000", "1600000"), "ITR-100": ("2500000", "1400000")}

BUSINESS_UNITS = [("SALES", "Sales", ["SAL"]),
                  ("CORP", "Corporate Services", ["HR", "FIN", "ICT", "FAC", "FLT", "SEC", "MKT", "FND", "CLN", "RSK"]),
                  ("OPS", "Operations", ["OPS", "CAT", "BUR", "ITR"])]
REGIONS = [("KZN", "KwaZulu-Natal"), ("GP", "Gauteng")]
BRANCHES = [("HO", "Head office", "KZN"), ("DBN", "Durban", "KZN"), ("PTN", "Pinetown", "KZN"),
            ("JHB", "Johannesburg", "GP")]
JOB_FAMILIES = [("SALES", "Sales"), ("HRM", "Human resources"), ("FINC", "Finance"), ("ICT", "ICT"),
                ("MGMT", "Management"), ("OPS", "Operations")]
FAMILY_FOR_DEPT = {"SAL": "SALES", "HR": "HRM", "FIN": "FINC", "OPS": "OPS", "ICT": "ICT"}   # anything else: OPS

# Demo budgeted CTC per position, by grade (grades themselves carry no salary).
DEMO_CTC = {"Intern": Decimal("90000"), "Junior": Decimal("180000"), "Senior": Decimal("360000"),
            "Manager": Decimal("720000"), "Exco": Decimal("1500000")}

# Vacant positions on the register: department, cost centre, title, grade name, seats, branch, family,
# reports to (username of the manager whose position it reports to), days vacant, minimum requirements.
VACANT_POSITIONS = [
    ("SAL", "SAL-100", "Funeral Policy Sales Consultant", "Junior", 4, "DBN", "SALES", "linemanager", 18,
     "Matric\n1 year of sales experience\nValid driver's licence"),
    ("SAL", "SAL-200", "Regional Sales Manager", "Manager", 1, "JHB", "MGMT", "hod", 74,
     "Bachelor's degree or diploma in sales or marketing\n5 years' sales management experience"),
    ("SAL", "SAL-100", "Head of Digital Sales", "Manager", 1, "HO", "MGMT", "hod", 41,
     "Bachelor's degree (NQF 7)\n8 years' experience, 3 in digital sales"),
    ("SAL", "SAL-100", "Sales Data Analyst", "Senior", 1, "HO", "SALES", "linemanager", 38,
     "Bachelor's degree (NQF 7) in Statistics, Mathematics or Information Systems\nSQL and Power BI"),
    ("SAL", "SAL-100", "Branch Administrator", "Junior", 1, "PTN", "SALES", "linemanager", 52, "Matric\nMS Office"),
    ("HR", "HR-200", "Talent Acquisition Specialist", "Senior", 1, "HO", "HRM", "hrmanager", 12,
     "Diploma in HR\n3 years' recruitment experience"),
    ("FIN", "FIN-100", "Payroll Officer", "Senior", 1, "HO", "FINC", "finance", 26,
     "Diploma in payroll or finance\nSage 300 People experience"),
    ("OPS", "OPS-200", "IT Support Technician", "Junior", 2, "HO", "ICT", "it", 96, "A+ / N+ certification\nDriver's licence"),
]


def main(accounts_only=False, department_accounts=False):
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
        grades = {g.name: g for g in JobGrade.query.all()}

        for cc_code, (amount, consumed) in ({} if accounts_only or department_accounts else BUDGETS).items():
            if not budget.get_line(centres[cc_code].id, fy):
                db.session.add(BudgetLine(cost_centre_id=centres[cc_code].id, financial_year=fy,
                                          amount=Decimal(amount), committed=0, consumed=Decimal(consumed)))

        roles = {r.name: r for r in Role.query.all()}
        if department_accounts:
            names = seed_department_accounts(depts, centres, grades, roles, password)
            seed_org_structure(depts)
            db.session.commit()
            print(f"Accounts created (password = SEED_PASSWORD from .env): {', '.join(names)}")
            return
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
        if accounts_only:
            db.session.commit()
            print(f"Accounts seeded: {', '.join(u[0] for u in USERS)} (password = SEED_PASSWORD from .env)")
            return
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
        seed_adverts(users)
        db.session.commit()

        print(f"Seed complete for {budget.fy_label(fy)}.")
        print(f"Test users (password = SEED_PASSWORD from .env): {', '.join(u[0] for u in USERS)}")
        print("To bring in the original portal's jobs, CVs and applications: flask import-legacy")


# Department accounts: the slug used in dm.<slug> / lm.<slug>, per department code.
DEPARTMENT_SLUGS = {"HR": "hr", "FIN": "finance", "SAL": "sales", "OPS": "operations", "CAT": "catering",
                    "BUR": "burials", "ICT": "ict", "FAC": "facilities", "FLT": "fleet", "SEC": "security",
                    "MKT": "marketing", "FND": "foundations", "CLN": "cleaning", "RSK": "risk", "ITR": "itravel"}
# username, full name, roles, department, grade name
ADMIN_ACCOUNTS = [
    ("exco", "Group Exco", ["GCOO", "Exco"], "OPS", "Exco"),
    ("hradmin", "HR Admin", ["HR Admin"], "HR", "Manager"),
    ("grouphr", "Group HR Manager", ["Group HR Manager"], "HR", "Manager"),
    ("finance", "Finance", ["Finance"], "FIN", "Manager"),
    ("it", "IT Administrator", ["IT"], "ICT", "Senior"),
]


def seed_department_accounts(depts, centres, grades, roles, password):
    """Admin accounts, then a Line Manager and a Department Manager per department. Line Managers report to Exco;
    each Department Manager reports to their department's Line Manager and is set as the department's head."""
    from app.models import Employee, User
    created = []

    def account(username, full_name, role_names, dept, grade, title, manager=None):
        user = User.query.filter_by(username=username).first()
        if user is not None:
            return user
        first, _, last = full_name.partition(" ")
        emp = Employee(employee_number=f"ICE{1001 + Employee.query.count()}", first_name=first,
                       last_name=last or first, email=f"{username}@icebolethu.co.za", department_id=dept.id,
                       cost_centre_id=dept.cost_centres[0].id, job_grade_id=grades[grade].id, position_title=title,
                       employment_type="Permanent", status="Permanent", start_date=date(2026, 1, 1),
                       manager_id=manager.employee_id if manager else None)
        db.session.add(emp)
        db.session.flush()
        user = User(username=username, full_name=full_name, email=emp.email, employee_id=emp.id, password_hash="")
        user.set_password(password)
        user.roles = [roles["Employee"]] + [roles[r] for r in role_names]
        db.session.add(user)
        db.session.flush()
        created.append(username)
        return user

    exco = None
    for username, full_name, role_names, d_code, grade in ADMIN_ACCOUNTS:
        user = account(username, full_name, role_names, depts[d_code], grade, full_name,
                       manager=exco if username != "exco" else None)
        exco = exco or user
    for code, _name, _centres, _hod in DEPARTMENTS:
        dept, slug = depts[code], DEPARTMENT_SLUGS[code]
        lm = account(f"lm.{slug}", f"{dept.name} Line Manager", ["Line Manager"], dept, "Manager",
                     f"{dept.name} Line Manager", manager=exco)
        # The HR Department Manager is also the HR Manager (approves job adverts), at the user's request (1 Nov 2026).
        dm_roles = ["Department Manager"] + (["HR Manager"] if code == "HR" else [])
        dm = account(f"dm.{slug}", f"{dept.name} Department Manager", dm_roles, dept, "Manager",
                     f"{dept.name} Department Manager", manager=lm)
        dept.hod_employee_id = dm.employee_id
    return created


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
    plus vacant and frozen seats. The register is approved. On a later run only test users without a position
    get one."""
    from app.models import ApprovedPosition, Branch, JobFamily, PositionRegister
    first_run = ApprovedPosition.query.first() is None
    from app.services.dates import today
    from app.services.refs import next_reference
    branches = {b.code: b for b in Branch.query.all()}
    families = {f.code: f for f in JobFamily.query.all()}

    def add(d_code, cc_code, title, grade, branch, family, reports_to=None, **extra):
        p = ApprovedPosition(position_number=next_reference("POS"), title=title, department_id=depts[d_code].id,
                             cost_centre_id=centres[cc_code].id, job_grade_id=grades[grade].id,
                             branch_id=branches[branch].id, job_family_id=families[family].id,
                             budgeted_ctc=DEMO_CTC[grade], financial_year=fy,
                             reports_to_id=reports_to.id if reports_to else None, **extra)
        db.session.add(p)
        db.session.flush()
        return p

    held = {}
    for username, _f, _l, _roles, d_code, cc_code, title, grade, manager in USERS:   # managers come first
        emp = users[username].employee
        if emp.approved_position is not None:
            held[username] = emp.approved_position
            continue
        branch = "DBN" if d_code == "SAL" and username in ("linemanager", "employee", "panel") else "HO"
        family = "MGMT" if grade in ("Manager", "Exco") else FAMILY_FOR_DEPT.get(d_code, "OPS")
        held[username] = add(d_code, cc_code, title, grade, branch, family, held.get(manager), status="Filled",
                             filled_on=date(2024, 1, 15))
        emp.approved_position_id = held[username].id
    if not first_run:
        return
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

    # An ad-hoc position the line manager needs, approved by the Department Manager and now waiting at Finance.
    sal = ApprovedPosition.query.filter_by(title="Sales Team Leader").first()
    inst = positions.request_ad_hoc({
        "title": "Claims Liaison Officer", "department_id": sal.department_id, "cost_centre_id": sal.cost_centre_id,
        "job_grade_id": ApprovedPosition.query.filter_by(title="Branch Administrator").first().job_grade_id,
        "branch_id": sal.branch_id, "reports_to_id": sal.id, "budgeted_ctc": None,
        "minimum_requirements": "Matric\n2 years' funeral claims experience",
        "justification": "Claims queries from the Durban branch now take a consultant away from sales for about "
                         "two days a week. A dedicated liaison officer would handle them."}, lm)
    workflow.act(inst.current_step, hod, "approve", "Agreed: the branch needs this role.")


# JD library: title, job family, description, required skills, qualification level, years, days to next review.
JD_LIBRARY = [
    ("Funeral Policy Sales Consultant", "SALES",
     "ABOUT THE ROLE\nSell and service Icebolethu funeral policies to families in the branch's area, with dignity "
     "and care.\n\nKEY RESPONSIBILITIES\n- Meet monthly new-business and retention targets\n- Explain cover "
     "options clearly and complete applications accurately\n- Follow up lapsed policies\n- Keep client records "
     "up to date and FAIS-compliant",
     "sales, customer service, fais", 1, 1, 300),
    ("Branch Administrator", "SALES",
     "ABOUT THE ROLE\nKeep the branch running: policy admin, cash-ups and client queries.\n\nKEY RESPONSIBILITIES"
     "\n- Capture new policies and changes\n- Daily cash-up and banking\n- Answer walk-in and phone queries",
     "ms office, admin, cash handling", 1, 2, 160),
    ("IT Support Technician", "ICT",
     "ABOUT THE ROLE\nFirst-line support for head office and the branches.\n\nKEY RESPONSIBILITIES\n- Log and "
     "resolve support calls\n- Set up laptops, phones and access\n- Visit branches for on-site fixes",
     "windows, networking, active directory", 3, 2, 20),
]
# Eight applicants for the seeded advert: name, email user, years, qualification, skills, status, channel.
ADVERT_APPLICANTS = [
    ("Sizwe Mthembu", "sizwe.m", 4, 2, "Sales, Customer service, FAIS, RE5", "Offer", "Careers site"),
    ("Ntombi Zungu", "ntombi.z", 3, 1, "Sales, Customer service, FAIS", "Interview", "LinkedIn"),
    ("Kabelo Moloi", "kabelo.m", 2, 1, "Sales, Customer service", "Shortlisted", "PNet"),
    ("Precious Hadebe", "precious.h", 5, 3, "Sales, FAIS, Funeral cover", "Shortlisted", "Careers site"),
    ("Musa Ngcobo", "musa.n", 1, 1, "Customer service", "Screening", "Internal"),
    ("Lungile Mabaso", "lungile.m", 2, 1, "Sales", "New", "LinkedIn"),
    ("Anele Cele", "anele.c", 0, 1, "Retail", "New", "Careers site"),
    ("Bheki Sithole", "bheki.s", 1, 0, "Driving", "Rejected", "PNet"),
]


def seed_adverts(users):
    """The JD library and one live advert with eight applicants at different stages (spec §11)."""
    from app.models import ApprovedPosition, AdvertPosting, Application, Candidate, Job, JobDescriptionTemplate, \
        JobFamily, Requisition
    from app.services import adverts, ats, positions, requisitions, workflow
    from app.services.dates import now, today
    families = {f.code: f for f in JobFamily.query.all()}
    for title, family, description, skills, edu, years, review_in in JD_LIBRARY:
        if not JobDescriptionTemplate.query.filter_by(title=title).first():
            db.session.add(JobDescriptionTemplate(
                title=title, job_family_id=families[family].id, description=description, required_skills=skills,
                min_education=edu, min_experience=years, review_date=today() + timedelta(days=review_in),
                active=True, updated_by_id=users["recruiter"].id))
    db.session.flush()
    if Job.query.filter(Job.reference.isnot(None)).first():
        return

    lm = users["linemanager"]
    position = next(p for p in ApprovedPosition.query.filter_by(title="Funeral Policy Sales Consultant", status="Vacant")
                    .order_by(ApprovedPosition.id) if positions.open_requisition(p) is None)
    req = Requisition()
    requisitions.apply_form(req, {"approved_position_id": position.id, "employment_type": "Permanent",
                                  "required_start_date": today() + timedelta(days=60), "is_executive": False,
                                  "justification": "A third consultant for Durban: new-business targets went up 30% "
                                                   "this year and the two consultants are fully booked."}, lm)
    requisitions.save(req, lm)
    inst = requisitions.submit(req, lm)
    while inst.status == "Pending":
        step = inst.current_step
        workflow.act(step, step.assignee, "approve", "Approved for the Durban branch.")

    job = adverts.draft_from_requisition(req, users["recruiter"])
    adverts.save(job, {"channels": ["Internal", "Intranet", "PNet", "LinkedIn"],
                       "location": job.location or "Durban, KwaZulu-Natal"}, users["recruiter"])
    inst = adverts.submit(job, users["recruiter"])
    workflow.act(inst.current_step, inst.current_step.assignee, "approve", "Good to publish.")
    db.session.flush()

    postings = {p.channel: p for p in AdvertPosting.query.filter_by(job_id=job.id)}
    for n, (name, handle, years, edu, skills, status, channel) in enumerate(ADVERT_APPLICANTS):
        cand = Candidate.query.filter_by(email=f"{handle}@example.test").first() or Candidate(
            full_name=name, email=f"{handle}@example.test", phone=f"082 555 {1000 + n}", location="Durban",
            years_experience=years, education_level=edu, skills=skills, consent=True, consent_at=now(), is_demo=True,
            cv_text=f"{name}\n{years} years' experience. Skills: {skills}. {ats.EDUCATION_LABELS.get(edu, '')}")
        db.session.add(cand)
        db.session.flush()
        score, breakdown = ats.score_candidate(job, cand)
        db.session.add(Application(reference=f"ICE-SEED{n:04d}", candidate_id=cand.id, job_id=job.id, score=score,
                                   breakdown=breakdown, status=status, source=channel))
        postings[channel].applications += 1
    for channel, views in {"Careers site": 64, "Internal": 12, "Intranet": 9, "PNet": 41, "LinkedIn": 57}.items():
        postings[channel].views = views


if __name__ == "__main__":
    main(accounts_only="--accounts-only" in sys.argv[1:], department_accounts="--department-accounts" in sys.argv[1:])
