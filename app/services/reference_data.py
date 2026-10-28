"""Reference data every installation needs (also used by the tests). Idempotent."""
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import JobGrade, PublicHoliday, Role, RoutingRule
from app.models.user import ALL_ROLES, FINANCE, GROUP_HR
from app.models.workflow import GCOO_OR_EXCO, LINE_MANAGER_OR_HOD
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
    "requisition": [
        (1, "Line manager", LINE_MANAGER_OR_HOD, "", 2),
        (2, "Finance / Budget Controller", FINANCE, "", 3),
        (3, "Group HR Manager", GROUP_HR, "", 3),
        (4, "GCOO / Exco", GCOO_OR_EXCO, "", 5),
    ],
    "adhoc_position": [
        (1, "Line manager", LINE_MANAGER_OR_HOD, "", 2),
        (2, "Finance (unbudgeted)", FINANCE, "", 3),
        (3, "Group HR Manager", GROUP_HR, "", 3),
        (4, "GCOO / Exco", GCOO_OR_EXCO, "", 5),
    ],
    "position_register": [
        (1, "Finance / Budget Controller", FINANCE, "", 5),
        (2, "Group HR Manager", GROUP_HR, "", 5),
    ],
    "position_change": [
        (1, "Finance / Budget Controller", FINANCE, "", 3),
        (2, "Group HR Manager", GROUP_HR, "", 3),
    ],
}

GRADE_NAMES = ["General Assistant", "Junior Administrator", "Administrator", "Senior Administrator",
               "Officer", "Senior Officer", "Specialist", "Senior Specialist", "Manager", "Senior Manager",
               "General Manager", "Executive"]


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
    """Grades 1–12. Bands grow ~28% a grade; the hourly rate is the midpoint over 2 080 hours."""
    for g in range(1, 13):
        if JobGrade.query.filter_by(grade=g).first():
            continue
        low = (Decimal(96000) * Decimal("1.28") ** (g - 1)).quantize(Decimal("1000"))
        high = (low * Decimal("1.45")).quantize(Decimal("1000"))
        rate = ((low + high) / 2 / 2080).quantize(Decimal("0.01"))
        db.session.add(JobGrade(grade=g, name=GRADE_NAMES[g - 1], band_min=low, band_max=high, hourly_rate=rate))


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
