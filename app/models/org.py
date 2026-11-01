"""Organisation: business units, departments, cost centres, regions and branches, job families, job grades,
the approved positions register, employees."""

from app.extensions import db
from app.models.base import EncryptedString, TimestampMixin

EMPLOYEE_STATUSES = ["Pre-boarding", "Probation", "Permanent", "Contract", "Casual", "Exited", "Archived"]
EMPLOYMENT_TYPES = ["Permanent", "Contract", "Casual"]

# Approved position statuses (spec §15.3). "Planned" positions wait for their year's register to be approved;
# "Pending approval" / "Returned" / "Rejected" are ad-hoc position requests.
POSITION_STATUSES = ["Planned", "Pending approval", "Returned", "Rejected", "Vacant", "In recruitment", "Filled",
                     "Frozen", "Abolished"]
OPEN_POSITION_STATUSES = ["Vacant", "In recruitment", "Filled", "Frozen"]   # on the approved register
REGISTER_STATUSES = ["Draft", "In Approval", "Approved", "Returned", "Rejected"]
POSITION_CHANGE_KINDS = ["Freeze", "Unfreeze", "Abolish", "Regrade"]


class BusinessUnit(db.Model):
    __tablename__ = "business_units"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return self.name


class Region(db.Model):
    __tablename__ = "regions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return self.name


class Branch(db.Model):
    """A branch or area (Head office, Durban, Pinetown...) in a region."""
    __tablename__ = "branches"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)

    region = db.relationship(Region)

    def __str__(self):
        return self.name


class JobFamily(db.Model):
    __tablename__ = "job_families"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return self.name


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    hod_employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", use_alter=True), index=True)
    business_unit_id = db.Column(db.Integer, db.ForeignKey("business_units.id"), index=True)
    # Pre-filled on a Department Manager's ad-hoc position request.
    job_family_id = db.Column(db.Integer, db.ForeignKey("job_families.id"), index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)

    hod = db.relationship("Employee", foreign_keys=[hod_employee_id], post_update=True)
    business_unit = db.relationship(BusinessUnit)
    job_family = db.relationship(JobFamily)
    cost_centres = db.relationship("CostCentre", back_populates="department", order_by="CostCentre.code")

    def __str__(self):
        return self.name


class CostCentre(db.Model):
    __tablename__ = "cost_centres"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)

    department = db.relationship(Department, back_populates="cost_centres")

    def __str__(self):
        return f"{self.code} · {self.name}"


class JobGrade(db.Model):
    """Job grade: Intern, Junior, Senior, Manager or Exco. `grade` is its rank (1–5) for ordering and routing-rule
    conditions such as `grade >= 4` (Manager and above). Grades carry no salary: a position's budgeted CTC does."""
    __tablename__ = "job_grades"
    id = db.Column(db.Integer, primary_key=True)
    grade = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)

    def __str__(self):
        return self.name


class PositionRegister(db.Model):
    """The approved positions register for one financial year, approved by Finance and the Group HR Manager."""
    __tablename__ = "position_registers"
    id = db.Column(db.Integer, primary_key=True)
    financial_year = db.Column(db.Integer, unique=True, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Draft", index=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)

    submitted_by = db.relationship("User")


class ApprovedPosition(TimestampMixin, db.Model):
    """One approved position (one seat) on the register (spec §15.3)."""
    __tablename__ = "approved_positions"
    id = db.Column(db.Integer, primary_key=True)
    position_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"), index=True)
    job_grade_id = db.Column(db.Integer, db.ForeignKey("job_grades.id"), index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    job_family_id = db.Column(db.Integer, db.ForeignKey("job_families.id"), index=True)
    reports_to_id = db.Column(db.Integer, db.ForeignKey("approved_positions.id"), index=True)
    budgeted_ctc = db.Column(db.Numeric(14, 2))
    minimum_requirements = db.Column(db.Text)
    financial_year = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Planned", index=True)
    critical = db.Column(db.Boolean, default=False, nullable=False)

    # Ad-hoc positions (an unplanned need, approved before a requisition can be raised)
    is_ad_hoc = db.Column(db.Boolean, default=False, nullable=False, index=True)
    justification = db.Column(db.Text)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", use_alter=True), index=True)

    # Vacancy tracking
    vacant_since = db.Column(db.Date, index=True)
    filled_on = db.Column(db.Date)
    days_to_fill = db.Column(db.Integer)
    last_holder_id = db.Column(db.Integer, db.ForeignKey("employees.id", use_alter=True), index=True)

    department = db.relationship(Department)
    cost_centre = db.relationship(CostCentre)
    job_grade = db.relationship(JobGrade)
    branch = db.relationship(Branch)
    job_family = db.relationship(JobFamily)
    reports_to = db.relationship("ApprovedPosition", remote_side=[id])
    requested_by = db.relationship("User")
    last_holder = db.relationship("Employee", foreign_keys=[last_holder_id], post_update=True)
    holders = db.relationship("Employee", foreign_keys="Employee.approved_position_id",
                              back_populates="approved_position")

    @property
    def business_unit(self):
        return self.department.business_unit if self.department else None

    @property
    def region(self):
        return self.branch.region if self.branch else None

    @property
    def holder(self):
        current = [e for e in self.holders if e.status not in ("Exited", "Archived")]
        return current[0] if current else None

    def __str__(self):
        return f"{self.position_number} · {self.title}"


class PositionChange(TimestampMixin, db.Model):
    """A requested freeze, unfreeze, abolish or regrade of a position, approved through the workflow engine."""
    __tablename__ = "position_changes"
    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey("approved_positions.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    new_job_grade_id = db.Column(db.Integer, db.ForeignKey("job_grades.id"))
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="In Approval", index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    position = db.relationship(ApprovedPosition, backref="changes")
    new_job_grade = db.relationship(JobGrade)
    requested_by = db.relationship("User")


class Employee(TimestampMixin, db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    employee_number = db.Column(db.String(20), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), index=True)
    phone = db.Column(db.String(40))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), index=True)
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"), index=True)
    job_grade_id = db.Column(db.Integer, db.ForeignKey("job_grades.id"), index=True)
    approved_position_id = db.Column(db.Integer, db.ForeignKey("approved_positions.id"), index=True)
    position_title = db.Column(db.String(160))
    manager_id = db.Column(db.Integer, db.ForeignKey("employees.id"), index=True)
    start_date = db.Column(db.Date, index=True)
    end_date = db.Column(db.Date)
    employment_type = db.Column(db.String(20), default="Permanent")
    status = db.Column(db.String(20), default="Permanent", nullable=False, index=True)
    critical_role = db.Column(db.Boolean, default=False, nullable=False)

    # Sensitive (POPIA): shown only to permitted roles; ID and bank encrypted at rest.
    id_number = db.Column(EncryptedString)
    bank_account = db.Column(EncryptedString)
    date_of_birth = db.Column(db.Date)
    race = db.Column(db.String(40))
    gender = db.Column(db.String(40))
    disability = db.Column(db.String(40))

    department = db.relationship(Department, foreign_keys=[department_id])
    cost_centre = db.relationship(CostCentre)
    job_grade = db.relationship(JobGrade)
    approved_position = db.relationship(ApprovedPosition, foreign_keys=[approved_position_id],
                                        back_populates="holders")
    manager = db.relationship("Employee", remote_side=[id], backref="direct_reports")
    user = db.relationship("User", back_populates="employee", uselist=False,
                           foreign_keys="User.employee_id")
    assets = db.relationship("Asset", back_populates="employee", order_by="Asset.issued_on")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.full_name} ({self.employee_number})"


ASSET_STATUSES = ["Issued", "Returned", "Lost"]


class Asset(db.Model):
    """Asset register entry (laptop, phone, access card...) issued to an employee. Managed by ICT."""
    __tablename__ = "assets"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    asset_tag = db.Column(db.String(40), nullable=False)
    category = db.Column(db.String(60))
    description = db.Column(db.String(255))
    issued_on = db.Column(db.Date)
    returned_on = db.Column(db.Date)
    status = db.Column(db.String(20), default="Issued", nullable=False)

    employee = db.relationship(Employee, back_populates="assets")


class LeaveEntry(db.Model):
    """Mock leave calendar data used by the leave adapter (delegation hints)."""
    __tablename__ = "leave_entries"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    leave_type = db.Column(db.String(40), default="Annual")

    employee = db.relationship(Employee)
