"""Reference data every installation needs (also used by the tests). Idempotent."""
from datetime import date, timedelta

from app.extensions import db
from app.models import JobGrade, PublicHoliday, Role, RoutingRule
from app.models.user import ALL_ROLES, FINANCE, GROUP_HR, HR_MANAGER
from app.models.workflow import DEPARTMENT_LINE_MANAGER, DEPARTMENT_MANAGER, GCOO_OR_EXCO
from app.services import notifications, settings
from app.services.calendar import observed_holidays

FIXED_HOLIDAYS = [
    (1, 1, "New Year's Day"), (3, 21, "Human Rights Day"), (4, 27, "Freedom Day"), (5, 1, "Workers' Day"),
    (6, 16, "Youth Day"), (8, 9, "National Women's Day"), (9, 24, "Heritage Day"),
    (12, 16, "Day of Reconciliation"), (12, 25, "Christmas Day"), (12, 26, "Day of Goodwill"),
]
EASTER_SUNDAY = {2026: date(2026, 4, 5), 2027: date(2027, 3, 28)}

# Default approval chains (spec §15.3, decided 28 Oct 2026): workflow type -> [(level, name, approver, condition, SLA)].
DEFAULT_RULES = {
    # Decided 31 Oct 2026: Department Manager → Line Manager → Finance → Group HR → Exco. The Department Manager
    # step applies when HR raises it (a Department Manager raising it starts at their Line Manager).
    "requisition": [
        (1, "Department manager", DEPARTMENT_MANAGER, 'raised_by == "HR"', 2),
        (2, "Line manager", DEPARTMENT_LINE_MANAGER, "", 2),
        (3, "Finance", FINANCE, "", 3),
        (4, "Group HR Manager", GROUP_HR, "", 3),
        (5, "GCOO / Exco", GCOO_OR_EXCO, "", 5),
    ],
    # Decided 31 Oct 2026: a manager's request goes to Finance then Exco; HR's request starts with the
    # Department Manager of the position's department.
    "adhoc_position": [
        (1, "Department manager", DEPARTMENT_MANAGER, 'raised_by == "HR"', 2),
        (2, "Finance (unbudgeted)", FINANCE, "", 3),
        (3, "GCOO / Exco", GCOO_OR_EXCO, "", 5),
    ],
    "position_register": [
        (1, "Finance", FINANCE, "", 5),
        (2, "Group HR Manager", GROUP_HR, "", 5),
    ],
    "position_change": [
        (1, "Finance", FINANCE, "", 3),
        (2, "Group HR Manager", GROUP_HR, "", 3),
    ],
    "advert": [  # spec §4.4: the HR Manager approves every advert before it is published
        (1, "HR Manager", HR_MANAGER, "", 2),
    ],
}

# Job grades by rank (decided 31 Oct 2026; they replace grades 1–12 and carry no salary).
GRADES = [(1, "Intern"), (2, "Junior"), (3, "Senior"), (4, "Manager"), (5, "Exco")]


def sa_public_holidays(year):
    easter = EASTER_SUNDAY[year]
    movable = [(easter - timedelta(days=2), "Good Friday"), (easter + timedelta(days=1), "Family Day")]
    return observed_holidays(year, FIXED_HOLIDAYS, movable)


def seed_roles():
    for name in ALL_ROLES:
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name))
    db.session.flush()


def seed_holidays(years=(2026, 2027)):
    for year in years:
        for d, name in sa_public_holidays(year):
            if not PublicHoliday.query.filter_by(date=d).first():
                db.session.add(PublicHoliday(date=d, name=name))


def seed_grades():
    for rank, name in GRADES:
        if not JobGrade.query.filter_by(grade=rank).first():
            db.session.add(JobGrade(grade=rank, name=name))


def seed_rules():
    """Default chains for any workflow type that has no active routing rules yet."""
    for workflow_type, rules in DEFAULT_RULES.items():
        if RoutingRule.query.filter_by(workflow_type=workflow_type, active=True).first():
            continue
        for level, name, approver, condition, sla in rules:
            db.session.add(RoutingRule(workflow_type=workflow_type, level=level, name=name, approver=approver,
                                       condition=condition, sla_days=sla))


def seed_reference_data():
    seed_roles()
    settings.ensure_defaults()
    notifications.ensure_templates()
    seed_holidays()
    seed_grades()
    seed_rules()
    db.session.flush()
