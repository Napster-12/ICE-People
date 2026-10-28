"""Phase 1: calendar, references, conditions, audit, notifications, integrations, encryption, SA ID."""
import threading
from datetime import date, datetime

import pytest

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import AuditLog, Employee, IntegrationLog, Notification, PublicHoliday
from app.models.system import AuditImmutableError
from app.services import audit, calendar, conditions, notifications
from app.services.dates import format_date, format_money
from app.services.errors import DomainError, StateMachine
from app.services.refs import next_reference
from app.services.reference_data import sa_public_holidays
from app.services.validators import luhn_ok, validate_sa_id
from tests.conftest import user


# ------------------------------------------------------------------ locale

def test_money_and_date_format():
    assert format_money("1234567") == "R 1 234 567.00"
    assert format_money("-950.5") == "R -950.50"
    assert format_money("0") == "R 0.00"
    assert format_date(date(2026, 10, 24)) == "24 Oct 2026"


# ---------------------------------------------------------------- calendar

def test_sa_holidays_include_sunday_observance():
    days = dict(sa_public_holidays(2026))
    assert date(2026, 8, 10) in days            # Women's Day falls on a Sunday -> Monday off
    assert days[date(2026, 4, 3)] == "Good Friday"
    days_2027 = dict(sa_public_holidays(2027))
    assert date(2027, 3, 22) in days_2027        # Human Rights Day 2027 is a Sunday
    assert date(2027, 12, 27) in days_2027       # Day of Goodwill 2027 is a Sunday


def test_add_business_days_skips_weekend_and_holiday(app):
    # Thu 23 Apr 2026 + 2 business days: Fri 24, (weekend), Mon 27 is Freedom Day -> Tue 28.
    assert calendar.add_business_days(date(2026, 4, 23), 2) == date(2026, 4, 28)
    start = datetime(2026, 4, 23, 9, 30)
    assert calendar.add_business_days(start, 2) == datetime(2026, 4, 28, 9, 30)


def test_business_days_between_and_hours(app):
    assert calendar.business_days_between(date(2026, 12, 24), date(2026, 12, 29)) == 2  # 25,26 holiday, 27 Sun
    # Fri 09:00 -> Mon 09:00 counts only Friday's remaining 15 hours and Monday's 9.
    assert calendar.business_hours_between(datetime(2026, 10, 23, 9), datetime(2026, 10, 26, 9)) == 24
    assert calendar.business_hours_between(datetime(2026, 10, 24, 9), datetime(2026, 10, 25, 9)) == 0


def test_holiday_table_is_configurable(app):
    d = date(2026, 11, 2)  # an ordinary Monday
    assert calendar.is_business_day(d)
    db.session.add(PublicHoliday(date=d, name="Company day"))
    db.session.flush()
    assert not calendar.is_business_day(d)


# --------------------------------------------------------------- references

def test_reference_format_and_sequence(app):
    a = next_reference("REQ", 2026)
    b = next_reference("REQ", 2026)
    c = next_reference("REQ", 2027)
    assert (a, b, c) == ("REQ-2026-00001", "REQ-2026-00002", "REQ-2027-00001")
    assert next_reference("EXT", 2026) == "EXT-2026-00001"
    with pytest.raises(ValueError):
        next_reference("XYZ")


def test_references_unique_across_threads(app, tmp_path):
    """Two sessions saving at once never get the same number (file DB so threads share it)."""
    from app import create_app
    app2 = create_app("testing", {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'refs.db'}",
                                  "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}}})
    with app2.app_context():
        db.create_all()
        db.session.commit()
    results, errors = [], []

    def worker():
        try:
            with app2.app_context():
                for _ in range(10):
                    results.append(next_reference("OFR", 2026))
                    db.session.commit()
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 40 and len(set(results)) == 40


# --------------------------------------------------------------- conditions

@pytest.mark.parametrize("expr,expected", [
    ("", True), ("all", True), ("grade >= 8", True), ("grade >= 10", False),
    ('headcount_type == "New" or is_over_budget', False), ("not is_executive", True),
    ('employment_type in ["Contract", "Casual"]', True),
])
def test_condition_evaluation(expr, expected):
    ctx = {"grade": 9, "headcount_type": "Replacement", "is_over_budget": False, "is_executive": False,
           "employment_type": "Contract"}
    assert conditions.evaluate(expr, ctx) is expected


@pytest.mark.parametrize("expr", ["__import__('os')", "grade.real", "x[0]", "lambda: 1", "unknown_field == 1",
                                  "grade >"])
def test_condition_rejects_unsafe_or_invalid(expr):
    with pytest.raises(conditions.ConditionError):
        conditions.evaluate(expr, {"grade": 1, "x": [1]})


# ------------------------------------------------------------ state machine

def test_state_machine():
    sm = StateMachine("thing", {"A": {"B"}, "B": set()})
    sm.check("A", "B")
    with pytest.raises(DomainError, match="can't move from B to A"):
        sm.check("B", "A")


# -------------------------------------------------------------------- audit

def test_audit_is_append_only(app):
    entry = audit.record("test.action", "thing", 1, before={"a": 1}, after={"a": 2}, user=user("hradmin"))
    db.session.commit()
    entry.action = "tampered"
    with pytest.raises(AuditImmutableError):
        db.session.commit()
    db.session.rollback()
    db.session.delete(db.session.get(AuditLog, entry.id))
    with pytest.raises(AuditImmutableError):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(AuditLog, entry.id).action == "test.action"


def test_no_audit_edit_routes(app):
    rules = [r for r in app.url_map.iter_rules() if "audit" in r.rule]
    assert all(r.methods <= {"GET", "HEAD", "OPTIONS"} for r in rules)


# ------------------------------------------------------------ notifications

def test_notification_template_is_rendered_and_emailed(app):
    u = user("finance")
    notifications.notify(u, "requisition_status", link="/x", ref="REQ-2026-00009", title="Clerk",
                         status="Approved", comment=None)
    db.session.flush()
    note = Notification.query.filter_by(user_id=u.id).one()
    assert note.title == "REQ-2026-00009: Clerk is now Approved"
    assert IntegrationLog.query.filter_by(system="email", method="send_email", success=True).count() == 1


def test_notification_templates_are_sandboxed(app):
    from app.models import NotificationTemplate
    tpl = NotificationTemplate.query.filter_by(key="requisition_status").one()
    tpl.subject = "{{ ''.__class__.__mro__ }}"
    with pytest.raises(Exception):
        notifications.render("requisition_status", {})


# ------------------------------------------------------------- integrations

def test_integration_retry_then_success_is_logged(app):
    payroll = get_adapter("payroll")
    payroll.forced_failures["push_status_change"] = 2   # fails twice, third attempt works (2 retries)
    emp = Employee.query.first()
    assert payroll.push_status_change(emp, "Permanent") == {"status": "accepted"}
    logs = IntegrationLog.query.filter_by(system="payroll", method="push_status_change").all()
    assert [l.success for l in logs] == [False, False, True]
    assert [l.attempt for l in logs] == [1, 2, 3]


def test_integration_gives_up_after_retries(app):
    directory = get_adapter("directory")
    directory.forced_failures["disable_user"] = 5
    with pytest.raises(IntegrationError):
        directory.disable_user(Employee.query.first())
    directory.forced_failures.clear()
    assert IntegrationLog.query.filter_by(system="directory", success=False).count() == 3


def test_every_integration_has_a_mock(app):
    for system in app.config["INTEGRATIONS"]:
        assert get_adapter(system) is not None


def test_ics_invite():
    from app.integrations.email_calendar import build_ics
    ics = build_ics("Interview", datetime(2026, 11, 3, 10, 0), 60, ["a@x.test"])
    assert "DTSTART;TZID=Africa/Johannesburg:20261103T100000" in ics and "ATTENDEE;RSVP=TRUE:mailto:a@x.test" in ics


# ------------------------------------------------------------ data at rest

def test_sensitive_columns_encrypted_at_rest(app):
    emp = Employee.query.first()
    emp.id_number = "8001015009087"
    emp.bank_account = "62001234567"
    db.session.commit()
    raw = db.session.execute(db.text("SELECT id_number, bank_account FROM employees WHERE id = :i"),
                             {"i": emp.id}).one()
    assert "8001015009087" not in raw[0] and "62001234567" not in raw[1]
    db.session.expire_all()
    assert db.session.get(Employee, emp.id).id_number == "8001015009087"


# ------------------------------------------------------------------- SA ID

def test_sa_id_validation():
    assert luhn_ok("8001015009087")
    assert validate_sa_id("8001015009087") == []
    assert validate_sa_id("8001015009087", date(1980, 1, 1)) == []
    assert "check digit" in validate_sa_id("8001015009088")[0]
    assert validate_sa_id("800101500908") == ["An SA ID number has 13 digits."]
    assert "date of birth" in validate_sa_id("8013015009087")[0]
    assert any("match" in p for p in validate_sa_id("8001015009087", date(1980, 1, 2)))
