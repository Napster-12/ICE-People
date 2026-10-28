from app.extensions import db
from app.models.base import TimestampMixin

REQUISITION_STATUSES = ["Draft", "Submitted", "In Approval", "Approved", "Advertised", "Interviewing",
                        "Offer", "Filled", "Returned", "Rejected", "Cancelled"]
HEADCOUNT_TYPES = ["New", "Replacement"]


class Requisition(TimestampMixin, db.Model):
    __tablename__ = "requisitions"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), index=True)
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"), index=True)
    job_grade_id = db.Column(db.Integer, db.ForeignKey("job_grades.id"), index=True)
    employment_type = db.Column(db.String(20), index=True)
    headcount_type = db.Column(db.String(20))
    replaced_employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), index=True)
    contract_end_date = db.Column(db.Date)
    required_start_date = db.Column(db.Date, index=True)
    estimated_hours = db.Column(db.Integer)
    is_executive = db.Column(db.Boolean, default=False, nullable=False)
    justification = db.Column(db.Text)
    approved_position_id = db.Column(db.Integer, db.ForeignKey("approved_positions.id"), index=True)

    status = db.Column(db.String(20), nullable=False, default="Draft", index=True)
    originator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False, default=0)
    submitted_at = db.Column(db.DateTime, index=True)
    approved_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)

    # Budget snapshot taken on submit (BU-003)
    financial_year = db.Column(db.Integer, index=True)
    ctc = db.Column(db.Numeric(14, 2))
    budget_line_id = db.Column(db.Integer, db.ForeignKey("budget_lines.id"))
    budget_available = db.Column(db.Numeric(14, 2))
    budget_shortfall = db.Column(db.Numeric(14, 2))
    is_over_budget = db.Column(db.Boolean, default=False, nullable=False)
    budget_snapshot_at = db.Column(db.DateTime)
    committed_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    consumed_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    department = db.relationship("Department")
    cost_centre = db.relationship("CostCentre")
    job_grade = db.relationship("JobGrade")
    replaced_employee = db.relationship("Employee")
    approved_position = db.relationship("ApprovedPosition")
    originator = db.relationship("User")
    budget_line = db.relationship("BudgetLine")
    versions = db.relationship("RequisitionVersion", back_populates="requisition",
                               order_by="RequisitionVersion.version.desc()")


class RequisitionVersion(db.Model):
    """Snapshot of the requisition each time it is submitted (version history)."""
    __tablename__ = "requisition_versions"
    id = db.Column(db.Integer, primary_key=True)
    requisition_id = db.Column(db.Integer, db.ForeignKey("requisitions.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False)

    requisition = db.relationship(Requisition, back_populates="versions")
    created_by = db.relationship("User")
