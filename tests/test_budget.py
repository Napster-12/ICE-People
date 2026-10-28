"""Phase 2: CTC, financial years, availability, commit/consume/release, CSV import, overspend alerts."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import BudgetLine, CostCentre, JobGrade, Notification, OverspendAlert
from app.services import budget
from app.services.dates import today
from app.services.errors import DomainError
from tests.conftest import financial_year, login, make_requisition, user


def grade(n):
    return JobGrade.query.filter_by(grade=n).first()


def test_ctc_permanent_is_band_midpoint(app):
    g = grade(5)
    assert budget.calculate_ctc(g, "Permanent") == ((g.band_min + g.band_max) / 2).quantize(Decimal("0.01"))


def test_ctc_contract_is_prorated_by_months(app):
    g = grade(5)
    ctc = budget.calculate_ctc(g, "Contract", date(2026, 3, 1), date(2026, 8, 31))
    assert ctc == (g.midpoint * 6 / 12).quantize(Decimal("0.01"))
    with pytest.raises(DomainError):
        budget.calculate_ctc(g, "Contract", date(2026, 3, 1), None)


def test_ctc_casual_is_hourly_rate_times_hours(app):
    g = grade(2)
    assert budget.calculate_ctc(g, "Casual", estimated_hours=100) == (g.hourly_rate * 100).quantize(Decimal("0.01"))
    assert isinstance(budget.calculate_ctc(g, "Casual", estimated_hours=100), Decimal)


@pytest.mark.parametrize("start,end,months", [
    (date(2026, 3, 1), date(2026, 3, 31), 1), (date(2026, 3, 15), date(2026, 4, 14), 1),
    (date(2026, 3, 15), date(2026, 4, 15), 2), (date(2026, 1, 1), date(2026, 12, 31), 12)])
def test_contract_months(start, end, months):
    assert budget.contract_months(start, end) == months


@pytest.mark.parametrize("d,fy", [(date(2027, 2, 28), 2026), (date(2027, 3, 1), 2027), (date(2026, 3, 1), 2026),
                                  (date(2026, 2, 28), 2025), (date(2028, 2, 29), 2027)])
def test_financial_year_feb_march_edges(d, fy):
    assert budget.financial_year_for(d, start_month=3) == fy


def test_financial_year_parsing_and_label():
    assert budget.parse_fy("2026/27") == budget.parse_fy("FY2026/27") == budget.parse_fy(2026) == 2026
    assert budget.fy_label(2026) == "FY2026/27"
    with pytest.raises(ValueError):
        budget.parse_fy("2026/28")
    assert budget.fy_bounds(2026, 3) == (date(2026, 3, 1), date(2027, 2, 28))


def test_snapshot_flags_over_budget(app):
    for line in BudgetLine.query.all():
        line.amount = Decimal("100000")
    req = make_requisition(user("linemanager"))
    assert req.is_over_budget
    assert req.budget_shortfall == req.ctc - Decimal("100000")
    assert req.budget_snapshot_at is not None


def test_commit_consume_release(app):
    req = make_requisition(user("linemanager"), submit=False)
    from app.services import requisitions
    requisitions.submit(req, user("linemanager"))
    line = req.budget_line
    budget.commit(req)
    assert line.committed == req.ctc and line.available == Decimal("5000000") - req.ctc
    budget.commit(req)                      # committing twice is a no-op
    assert line.committed == req.ctc
    budget.consume(req)
    assert line.committed == 0 and line.consumed == req.ctc and req.committed_amount == 0
    req2 = make_requisition(user("linemanager"))
    budget.commit(req2)
    budget.release(req2)
    assert Decimal(line.committed) == 0 and req2.committed_amount == 0


def test_close_unfilled_releases_budget(app):
    from app.services import requisitions, workflow
    req = make_requisition(user("employee"))
    inst = workflow.latest_instance("requisition", req.id)
    for actor in ("linemanager", "finance", "grouphr", "gcoo"):
        workflow.act(inst.current_step, user(actor), "approve", "ok")
    assert req.status == "Approved" and req.committed_amount > 0
    assert req.approved_position.status == "In recruitment"
    with pytest.raises(DomainError):
        requisitions.cancel(req, user("employee"))
    with pytest.raises(DomainError):
        requisitions.close_unfilled(req, user("hrbp"), "")
    requisitions.close_unfilled(req, user("hrbp"), "Role no longer needed")
    assert req.status == "Cancelled" and Decimal(req.budget_line.committed) == 0
    assert req.approved_position.status == "Vacant"


def test_line_amount_cannot_go_below_committed_plus_consumed(app):
    line = BudgetLine.query.first()
    line.committed, line.consumed = Decimal("100"), Decimal("50")
    with pytest.raises(DomainError):
        budget.set_line_amount(line, "149.99")
    budget.set_line_amount(line, "150")
    assert line.amount == Decimal("150.00")


def test_overspend_alert_once_per_day(app):
    line = BudgetLine.query.first()
    line.amount, line.consumed = Decimal("1000"), Decimal("950")
    assert budget.check_overspend(line) is True
    assert budget.check_overspend(line) is False
    assert OverspendAlert.query.count() == 1
    assert Notification.query.filter_by(user_id=user("finance").id).count() == 1


def test_overspend_below_threshold(app):
    line = BudgetLine.query.first()
    line.amount, line.consumed = Decimal("1000"), Decimal("899")
    assert budget.check_overspend(line) is False


CSV_HEAD = "department_code,cost_centre_code,financial_year,amount\n"


def test_csv_import_all_or_nothing(app):
    fy = financial_year()
    bad = CSV_HEAD + f"SAL,SAL-100,{fy + 1}/{(fy + 2) % 100:02d},1000000\nSAL,HR-100,{fy + 1},5\nXX,SAL-100,2026,abc\n"
    saved, errors = budget.import_csv(bad)
    assert saved == 0 and len(errors) == 2
    assert "Row 3" in errors[0] and "doesn't belong" in errors[0]
    assert "Row 4" in errors[1] and "unknown department" in errors[1] and "valid number" in errors[1]
    db.session.flush()
    assert BudgetLine.query.filter_by(financial_year=fy + 1).count() == 0
    good = CSV_HEAD + f"SAL,SAL-100,{fy + 1},1000000\nHR,HR-100,FY{fy + 1}/{(fy + 2) % 100:02d},2 500 000.50\n"
    saved, errors = budget.import_csv(good)
    assert (saved, errors) == (2, [])
    hr_line = BudgetLine.query.join(CostCentre).filter(CostCentre.code == "HR-100",
                                                       BudgetLine.financial_year == fy + 1).one()
    assert hr_line.amount == Decimal("2500000.50")


def test_csv_import_rejects_bad_header_duplicates_and_floor(app):
    assert budget.import_csv("a,b,c,d\n")[1][0].startswith("Row 1")
    fy = financial_year()
    dup = CSV_HEAD + f"SAL,SAL-100,{fy},1\nSAL,SAL-100,{fy},2\n"
    errors = budget.import_csv(dup)[1]
    assert any("more than once" in e for e in errors)
    assert any("below committed" in e for e in errors) is False
    line = BudgetLine.query.join(CostCentre).filter(CostCentre.code == "SAL-100").first()
    line.committed = Decimal("10")
    errors = budget.import_csv(CSV_HEAD + f"SAL,SAL-100,{fy},5\n")[1]
    assert "below committed" in errors[0]


def test_budget_screens(client):
    login(client, "finance")
    assert client.get("/budget/").status_code == 200
    assert client.get("/budget/report").status_code == 200
    assert client.get("/budget/report?format=csv").mimetype == "text/csv"
    assert b"department_code" in client.get("/budget/import/template.csv").data
    line = BudgetLine.query.first()
    r = client.post(f"/budget/{line.id}/edit", data={"amount": "6000000"})
    assert r.status_code == 302 and db.session.get(BudgetLine, line.id).amount == Decimal("6000000")
    from app.models import AuditLog
    assert AuditLog.query.filter_by(entity="budget_line", action="update").count() == 1


def test_salary_bands_editable_by_hr_admin_only(client):
    g = grade(3)
    data = {f"min_{x.id}": x.band_min for x in JobGrade.query.all()}
    data.update({f"max_{x.id}": x.band_max for x in JobGrade.query.all()})
    data.update({f"rate_{x.id}": x.hourly_rate for x in JobGrade.query.all()})
    data[f"max_{g.id}"] = "999999"
    login(client, "finance")
    assert client.get("/budget/salary-bands").status_code == 200
    assert client.post("/budget/salary-bands", data=data).status_code == 403
    client.post("/logout")
    login(client, "hradmin")
    assert client.post("/budget/salary-bands", data=data).status_code == 302
    assert grade(3).band_max == Decimal("999999")
    data[f"max_{g.id}"] = "1"
    client.post("/budget/salary-bands", data=data)
    assert grade(3).band_max == Decimal("999999")      # max below min rejected
