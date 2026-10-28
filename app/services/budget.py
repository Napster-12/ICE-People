"""Budget rules: CTC, financial years, availability, commit / consume / release, CSV import."""
import csv
import io
import math
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models import BudgetLine, BudgetMovement, CostCentre, Department, OverspendAlert
from app.models.user import FINANCE
from app.services import audit, settings
from app.services.dates import format_money, today
from app.services.errors import DomainError
from app.services.notifications import notify, users_with_role

CENTS = Decimal("0.01")


# --------------------------------------------------------- financial years

def financial_year_for(d, start_month=None):
    """The FY a date falls in, named by its starting calendar year.
    With a March start: 28 Feb 2027 -> 2026 (FY2026/27); 1 Mar 2027 -> 2027."""
    start_month = start_month or settings.get("fy_start_month", int)
    return d.year if d.month >= start_month else d.year - 1


def fy_label(year):
    return f"FY{year}/{str(year + 1)[-2:]}"


def fy_bounds(year, start_month=None):
    start_month = start_month or settings.get("fy_start_month", int)
    start = date(year, start_month, 1)
    return start, date.fromordinal(date(year + 1, start_month, 1).toordinal() - 1)


def parse_fy(value):
    """Accepts 2026, '2026', '2026/27', 'FY2026/27' or '2026-27'."""
    m = re.fullmatch(r"\s*(?:FY)?\s*(\d{4})(?:\s*[/-]\s*(\d{2}|\d{4}))?\s*", str(value or ""), re.I)
    if not m:
        raise ValueError("Financial year must look like 2026 or 2026/27.")
    year = int(m.group(1))
    if m.group(2):
        tail = int(m.group(2)[-2:])
        if tail != (year + 1) % 100:
            raise ValueError(f"{value} isn't a valid financial year.")
    return year


# --------------------------------------------------------------------- CTC

def contract_months(start, end):
    """Whole months covered by a contract, counting a part month as a full month."""
    if not start or not end or end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day >= start.day:
        months += 1
    return max(1, months)


def calculate_ctc(grade, employment_type, start_date=None, end_date=None, estimated_hours=None):
    """Annual-cost estimate for a requisition (Decimal, 2dp).

    Permanent: salary band midpoint. Contract: midpoint pro-rated by contract months.
    Casual: hourly rate x estimated hours."""
    if grade is None:
        raise DomainError("Choose a job grade to calculate the CTC.")
    midpoint = Decimal(grade.midpoint)
    if employment_type == "Contract":
        months = contract_months(start_date, end_date)
        if not months:
            raise DomainError("A contract role needs a start date and a contract end date after it.")
        return (midpoint * months / 12).quantize(CENTS)
    if employment_type == "Casual":
        hours = estimated_hours or settings.get("casual_default_hours", int)
        return (Decimal(grade.hourly_rate) * hours).quantize(CENTS)
    return midpoint.quantize(CENTS)


# ------------------------------------------------------------ availability

def get_line(cost_centre_id, financial_year):
    return BudgetLine.query.filter_by(cost_centre_id=cost_centre_id, financial_year=financial_year).first()


def available_budget(cost_centre_id, financial_year):
    line = get_line(cost_centre_id, financial_year)
    return line.available if line else Decimal("0.00")


def snapshot_requisition(req):
    """Record CTC, availability and shortfall on the requisition (BU-003)."""
    fy = financial_year_for(req.required_start_date or today())
    ctc = calculate_ctc(req.job_grade, req.employment_type, req.required_start_date,
                        req.contract_end_date, req.estimated_hours)
    line = get_line(req.cost_centre_id, fy)
    available = line.available if line else Decimal("0.00")
    req.financial_year = fy
    req.ctc = ctc
    req.budget_line_id = line.id if line else None
    req.budget_available = available
    req.budget_shortfall = max(Decimal("0.00"), ctc - available)
    req.is_over_budget = ctc > available
    from app.services.dates import now
    req.budget_snapshot_at = now()
    return req


# --------------------------------------------------------------- lifecycle

def _movement(line, req, kind, amount):
    db.session.add(BudgetMovement(budget_line_id=line.id, requisition_id=req.id if req else None,
                                  kind=kind, amount=amount))
    audit.record("budget." + kind, "budget_line", line.id,
                 after={"requisition": req.reference if req else None, "amount": str(amount),
                        "committed": str(line.committed), "consumed": str(line.consumed)})


def _line_for(req):
    line = req.budget_line or get_line(req.cost_centre_id, req.financial_year)
    if line is None:
        raise DomainError(f"There is no {fy_label(req.financial_year)} budget line for this cost centre.")
    return line


def commit(req):
    """On final approval: reserve the CTC against the cost centre's budget."""
    if Decimal(req.committed_amount or 0) > 0:
        return
    line = _line_for(req)
    amount = Decimal(req.ctc or 0)
    line.committed = Decimal(line.committed) + amount
    req.committed_amount = amount
    req.budget_line_id = line.id
    _movement(line, req, "commit", amount)
    check_overspend(line)


def consume(req, amount=None):
    """On offer acceptance: move the commitment to consumed (optionally at the actual offer amount)."""
    line = _line_for(req)
    committed = Decimal(req.committed_amount or 0)
    amount = Decimal(amount) if amount is not None else committed
    line.committed = Decimal(line.committed) - committed
    line.consumed = Decimal(line.consumed) + amount
    req.committed_amount = Decimal("0.00")
    req.consumed_amount = Decimal(req.consumed_amount or 0) + amount
    _movement(line, req, "consume", amount)
    check_overspend(line)


def release(req):
    """On cancel or close-unfilled: give the committed amount back."""
    committed = Decimal(req.committed_amount or 0)
    if committed <= 0:
        return
    line = _line_for(req)
    line.committed = Decimal(line.committed) - committed
    req.committed_amount = Decimal("0.00")
    _movement(line, req, "release", committed)


def check_overspend(line):
    """Alert Finance once per cost centre per day when usage passes the threshold."""
    threshold = settings.get("overspend_alert_pct", Decimal)
    if Decimal(line.amount) <= 0 or line.utilisation < threshold:
        return False
    day = today()
    if OverspendAlert.query.filter_by(cost_centre_id=line.cost_centre_id, alert_date=day).first():
        return False
    db.session.add(OverspendAlert(cost_centre_id=line.cost_centre_id, alert_date=day, utilisation=line.utilisation))
    used = Decimal(line.committed) + Decimal(line.consumed)
    notify(users_with_role(FINANCE), "budget_overspend", link=f"/budget/?fy={line.financial_year}",
           cost_centre=str(line.cost_centre), pct=line.utilisation, fy=fy_label(line.financial_year),
           used=format_money(used), amount=format_money(line.amount))
    return True


# ------------------------------------------------------------- maintenance

def set_line_amount(line, amount):
    amount = Decimal(amount).quantize(CENTS)
    floor = Decimal(line.committed) + Decimal(line.consumed)
    if amount < 0:
        raise DomainError("A budget amount can't be negative.")
    if amount < floor:
        raise DomainError(f"The amount can't be less than committed + consumed ({format_money(floor)}).")
    before = str(line.amount) if line.amount is not None else None
    line.amount = amount
    return before


CSV_COLUMNS = ["department_code", "cost_centre_code", "financial_year", "amount"]


def csv_template():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for cc in CostCentre.query.join(Department).order_by(Department.code, CostCentre.code):
        w.writerow([cc.department.code, cc.code, fy_label(financial_year_for(today()))[2:], "0.00"])
    return out.getvalue()


def import_csv(text):
    """All-or-nothing import. Returns (rows_saved, errors). Nothing is saved if any row fails."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    if header != CSV_COLUMNS:
        return 0, [f"Row 1: the header must be {', '.join(CSV_COLUMNS)}."]
    departments = {d.code.upper(): d for d in Department.query.all()}
    centres = {c.code.upper(): c for c in CostCentre.query.all()}
    errors, parsed, seen = [], [], set()
    for n, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        problems = []
        dept = departments.get(row["department_code"].upper())
        cc = centres.get(row["cost_centre_code"].upper())
        if dept is None:
            problems.append(f"unknown department '{row['department_code']}'")
        if cc is None:
            problems.append(f"unknown cost centre '{row['cost_centre_code']}'")
        elif dept is not None and cc.department_id != dept.id:
            problems.append(f"cost centre {cc.code} doesn't belong to {dept.code}")
        try:
            fy = parse_fy(row["financial_year"])
        except ValueError as exc:
            fy = None
            problems.append(str(exc))
        try:
            amount = Decimal(row["amount"].replace(" ", "").replace(",", ""))
            if not math.isfinite(amount) or amount < 0:
                raise InvalidOperation
            amount = amount.quantize(CENTS)
        except (InvalidOperation, ValueError):
            amount = None
            problems.append(f"amount '{row['amount']}' isn't a valid number")
        if cc is not None and fy is not None:
            if (cc.id, fy) in seen:
                problems.append(f"{cc.code} {fy_label(fy)} appears more than once")
            seen.add((cc.id, fy))
            line = get_line(cc.id, fy)
            if line is not None and amount is not None:
                floor = Decimal(line.committed) + Decimal(line.consumed)
                if amount < floor:
                    problems.append(f"amount is below committed + consumed ({format_money(floor)})")
        if problems:
            errors.append(f"Row {n}: " + "; ".join(problems) + ".")
        else:
            parsed.append((cc, fy, amount))
    if not parsed and not errors:
        errors.append("The file has no data rows.")
    if errors:
        return 0, errors
    for cc, fy, amount in parsed:
        line = get_line(cc.id, fy)
        if line is None:
            line = BudgetLine(cost_centre_id=cc.id, financial_year=fy, amount=amount, committed=0, consumed=0)
            db.session.add(line)
        else:
            line.amount = amount
    audit.record("budget.import", "budget_line", None, after={"rows": len(parsed)})
    return len(parsed), []


# ----------------------------------------------------------------- reports

def impact_report(financial_year):
    """Per department: budget, committed, consumed, available and requisition demand (BU-006)."""
    from app.models import Requisition
    rows = []
    for dept in Department.query.order_by(Department.name):
        lines = (BudgetLine.query.join(CostCentre)
                 .filter(CostCentre.department_id == dept.id, BudgetLine.financial_year == financial_year).all())
        reqs = Requisition.query.filter(Requisition.department_id == dept.id,
                                        Requisition.financial_year == financial_year).all()
        in_approval = [r for r in reqs if r.status in ("Submitted", "In Approval")]
        amount = sum((Decimal(l.amount) for l in lines), Decimal(0))
        committed = sum((Decimal(l.committed) for l in lines), Decimal(0))
        consumed = sum((Decimal(l.consumed) for l in lines), Decimal(0))
        pending = sum((Decimal(r.ctc or 0) for r in in_approval), Decimal(0))
        rows.append({
            "department": dept, "amount": amount, "committed": committed, "consumed": consumed,
            "available": amount - committed - consumed, "pending": pending,
            "requisitions": len(reqs), "over_budget": sum(1 for r in reqs if r.is_over_budget),
            "utilisation": ((committed + consumed) * 100 / amount).quantize(Decimal("0.1")) if amount else Decimal(0),
        })
    return rows
