from decimal import Decimal

from app.extensions import db
from app.models.base import TimestampMixin
from app.services.dates import now


class BudgetLine(TimestampMixin, db.Model):
    """Headcount budget for one cost centre in one financial year (FY starts in `financial_year`)."""
    __tablename__ = "budget_lines"
    __table_args__ = (db.UniqueConstraint("cost_centre_id", "financial_year"),)
    id = db.Column(db.Integer, primary_key=True)
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"), nullable=False, index=True)
    financial_year = db.Column(db.Integer, nullable=False, index=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    committed = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    consumed = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    cost_centre = db.relationship("CostCentre")

    @property
    def available(self):
        return Decimal(self.amount) - Decimal(self.committed) - Decimal(self.consumed)

    @property
    def utilisation(self):
        amount = Decimal(self.amount)
        if not amount:
            return Decimal(0)
        return ((Decimal(self.committed) + Decimal(self.consumed)) * 100 / amount).quantize(Decimal("0.1"))


class BudgetMovement(db.Model):
    """Commit / consume / release history for a budget line."""
    __tablename__ = "budget_movements"
    id = db.Column(db.Integer, primary_key=True)
    budget_line_id = db.Column(db.Integer, db.ForeignKey("budget_lines.id"), nullable=False, index=True)
    requisition_id = db.Column(db.Integer, db.ForeignKey("requisitions.id"), index=True)
    kind = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    budget_line = db.relationship(BudgetLine)


class OverspendAlert(db.Model):
    """One row per cost centre per day, so Finance is alerted at most once a day."""
    __tablename__ = "overspend_alerts"
    __table_args__ = (db.UniqueConstraint("cost_centre_id", "alert_date"),)
    id = db.Column(db.Integer, primary_key=True)
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"), nullable=False)
    alert_date = db.Column(db.Date, nullable=False)
    utilisation = db.Column(db.Numeric(6, 1), nullable=False)
