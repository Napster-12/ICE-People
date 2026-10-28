"""Finance screens: budget lines, CSV annual load, impact report; salary bands (REQ-BU-001–007)."""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.auth.decorators import roles_required
from app.extensions import db
from app.models import BudgetLine, BudgetMovement, CostCentre, Department, JobGrade
from app.models.user import FINANCE, GCOO, HR_ADMIN, HR_MANAGER
from app.services import audit, budget
from app.services.dates import format_money, to_decimal, today
from app.services.errors import DomainError
from app.web import paginate

bp = Blueprint("budget", __name__, url_prefix="/budget")
VIEW = (FINANCE, HR_ADMIN, HR_MANAGER, GCOO)
EDIT = (FINANCE, HR_ADMIN)


def _fy_choices():
    current = budget.financial_year_for(today())
    years = {current - 1, current, current + 1}
    years |= {fy for (fy,) in db.session.query(BudgetLine.financial_year).distinct()}
    return sorted(years)


@bp.route("/")
@roles_required(*VIEW)
def index():
    fy = request.args.get("fy", type=int) or budget.financial_year_for(today())
    q = (BudgetLine.query.options(joinedload(BudgetLine.cost_centre).joinedload(CostCentre.department))
         .join(CostCentre).join(Department).filter(BudgetLine.financial_year == fy))
    if request.args.get("department_id", type=int):
        q = q.filter(CostCentre.department_id == request.args.get("department_id", type=int))
    lines = q.order_by(Department.name, CostCentre.code).all()
    totals = {k: sum((Decimal(getattr(l, k)) for l in lines), Decimal(0)) for k in ("amount", "committed", "consumed")}
    totals["available"] = totals["amount"] - totals["committed"] - totals["consumed"]
    lines, pager = paginate(lines, 30)
    return render_template("budget/index.html", lines=lines, pager=pager, fy=fy, fy_label=budget.fy_label,
                           years=_fy_choices(), totals=totals, departments=Department.query.order_by(Department.name),
                           can_edit=current_user.has_role(*EDIT), args=request.args)


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:line_id>/edit", methods=["GET", "POST"])
@roles_required(*EDIT)
def edit(line_id=None):
    line = db.session.get(BudgetLine, line_id) if line_id else None
    if line_id and line is None:
        abort(404)
    if request.method == "POST":
        amount = to_decimal(request.form.get("amount"))
        try:
            if amount is None:
                raise DomainError("Enter the budget amount.")
            if line is None:
                cc = db.session.get(CostCentre, request.form.get("cost_centre_id", type=int) or 0)
                fy = budget.parse_fy(request.form.get("financial_year", ""))
                if cc is None:
                    raise DomainError("Choose a cost centre.")
                if budget.get_line(cc.id, fy):
                    raise DomainError(f"{cc.code} already has a {budget.fy_label(fy)} budget line. Edit it instead.")
                line = BudgetLine(cost_centre_id=cc.id, financial_year=fy, amount=0, committed=0, consumed=0)
                db.session.add(line)
                db.session.flush()
                budget.set_line_amount(line, amount)
                audit.record("create", "budget_line", line.id, after={"cost_centre": cc.code, "fy": fy,
                                                                     "amount": str(line.amount)})
            else:
                before = budget.set_line_amount(line, amount)
                audit.record("update", "budget_line", line.id, before={"amount": before},
                             after={"amount": str(line.amount)})
            db.session.commit()
            flash("Budget line saved.", "success")
            return redirect(url_for("budget.index", fy=line.financial_year))
        except (DomainError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
    movements = []
    if line:
        movements = (BudgetMovement.query.filter_by(budget_line_id=line.id)
                     .order_by(BudgetMovement.created_at.desc()).limit(50).all())
    cost_centres = CostCentre.query.join(Department).order_by(Department.name, CostCentre.code).all()
    return render_template("budget/form.html", line=line, cost_centres=cost_centres, movements=movements,
                           fy_label=budget.fy_label, current_fy=budget.financial_year_for(today()))


@bp.route("/import", methods=["GET", "POST"])
@roles_required(*EDIT)
def import_csv():
    errors = []
    if request.method == "POST":
        upload = request.files.get("file")
        if not upload or not upload.filename.lower().endswith(".csv"):
            errors = ["Choose a .csv file."]
        else:
            text = upload.read().decode("utf-8-sig", errors="replace")
            saved, errors = budget.import_csv(text)
            if errors:
                db.session.rollback()
                flash(f"Nothing was imported: {len(errors)} row(s) need fixing.", "error")
            else:
                db.session.commit()
                flash(f"Imported {saved} budget line(s).", "success")
                return redirect(url_for("budget.index"))
    return render_template("budget/import.html", errors=errors, columns=budget.CSV_COLUMNS)


@bp.route("/import/template.csv")
@roles_required(*EDIT)
def import_template():
    return Response(budget.csv_template(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=budget_template.csv"})


@bp.route("/report")
@roles_required(*VIEW)
def report():
    fy = request.args.get("fy", type=int) or budget.financial_year_for(today())
    rows = budget.impact_report(fy)
    if request.args.get("format") == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Department", "Budget", "Committed", "Consumed", "Available", "Pending approval",
                    "Requisitions", "Over budget", "Utilisation %"])
        for r in rows:
            w.writerow([r["department"].name, r["amount"], r["committed"], r["consumed"], r["available"],
                        r["pending"], r["requisitions"], r["over_budget"], r["utilisation"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=budget_impact_{fy}.csv"})
    return render_template("budget/report.html", rows=rows, fy=fy, fy_label=budget.fy_label, years=_fy_choices())


@bp.route("/salary-bands", methods=["GET", "POST"])
@roles_required(FINANCE, HR_ADMIN)
def salary_bands():
    grades = JobGrade.query.order_by(JobGrade.grade).all()
    if request.method == "POST":
        if not current_user.has_role(HR_ADMIN):
            abort(403)
        errors = []
        for g in grades:
            lo = to_decimal(request.form.get(f"min_{g.id}"))
            hi = to_decimal(request.form.get(f"max_{g.id}"))
            rate = to_decimal(request.form.get(f"rate_{g.id}"))
            if lo is None or hi is None or rate is None or lo < 0 or rate < 0:
                errors.append(f"Grade {g.grade}: enter valid amounts.")
                continue
            if hi < lo:
                errors.append(f"Grade {g.grade}: the maximum must be at least the minimum.")
                continue
            before = {"min": str(g.band_min), "max": str(g.band_max), "rate": str(g.hourly_rate)}
            after = {"min": str(lo.quantize(Decimal('0.01'))), "max": str(hi.quantize(Decimal('0.01'))),
                     "rate": str(rate.quantize(Decimal('0.01')))}
            if before != after:
                g.band_min, g.band_max, g.hourly_rate = lo, hi, rate
                audit.record("config.salary_band", "job_grade", g.id, before=before, after=after)
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, "error")
        else:
            db.session.commit()
            flash("Salary bands saved.", "success")
            return redirect(url_for("budget.salary_bands"))
    return render_template("budget/salary_bands.html", grades=grades, can_edit=current_user.has_role(HR_ADMIN),
                           money=format_money)
