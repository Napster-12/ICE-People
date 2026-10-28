from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask_login import UserMixin
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models.base import TimestampMixin

# ------------------------------------------------------------------ roles

EMPLOYEE = "Employee"
LINE_MANAGER = "Line Manager"
HOD = "HOD"
HRBP = "HR Business Partner"
RECRUITER = "Recruiter"
HR_MANAGER = "HR Manager"
GROUP_HR = "Group HR Manager"
HR_OD = "HR OD"
FINANCE = "Finance / Budget Controller"
PAYROLL = "Payroll"
IT = "IT"
ASSET_CONTROLLER = "Asset Controller"
COMPLIANCE = "Compliance"
GCOO = "GCOO"
HR_ADMIN = "HR Admin"
PANEL = "Panel Member"
EXCO = "Exco"

ALL_ROLES = [EMPLOYEE, LINE_MANAGER, HOD, HRBP, RECRUITER, HR_MANAGER, GROUP_HR, HR_OD, FINANCE,
             PAYROLL, IT, ASSET_CONTROLLER, COMPLIANCE, GCOO, EXCO, HR_ADMIN, PANEL]
HR_ROLES = {HRBP, RECRUITER, HR_MANAGER, GROUP_HR, HR_OD, HR_ADMIN}
# Roles that may see the executive / strategic flag ("HOD and above").
EXECUTIVE_ROLES = {HOD, HR_MANAGER, GROUP_HR, GCOO, EXCO, HR_ADMIN}
# Roles allowed to see sensitive personal fields (ID number, bank, demographics, health).
SENSITIVE_ROLES = {HR_MANAGER, GROUP_HR, HR_ADMIN, PAYROLL}
# Which sign-in landing page a user belongs to; the highest one wins.
ADMIN_PORTAL_ROLES = HR_ROLES | {FINANCE, PAYROLL, IT, ASSET_CONTROLLER, COMPLIANCE, GCOO, EXCO}
MANAGER_ROLES = {LINE_MANAGER, HOD}

_hasher = PasswordHasher()

user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<Role {self.name}>"


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), index=True)
    full_name = db.Column(db.String(160), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), unique=True, index=True)

    roles = db.relationship(Role, secondary=user_roles, lazy="selectin")
    employee = db.relationship("Employee", foreign_keys=[employee_id], back_populates="user")

    # Flask-Login
    @property
    def is_active(self):
        return self.active

    @property
    def role_names(self):
        return {r.name for r in self.roles}

    def has_role(self, *names):
        return bool(self.role_names & set(names))

    @property
    def landing(self):
        """The sign-in landing page for this user: "admin", "manager" or "staff"."""
        if self.role_names & ADMIN_PORTAL_ROLES:
            return "admin"
        return "manager" if self.role_names & MANAGER_ROLES else "staff"

    @property
    def is_hr(self):
        return bool(self.role_names & HR_ROLES)

    @property
    def can_see_sensitive(self):
        return bool(self.role_names & SENSITIVE_ROLES)

    @property
    def department_id(self):
        return self.employee.department_id if self.employee else None

    def set_password(self, password):
        self.password_hash = _hasher.hash(password)

    def check_password(self, password):
        """Argon2, with fallback for werkzeug hashes imported from the old portal.
        Returns True when the password matches; legacy hashes are upgraded."""
        if self.password_hash.startswith("$argon2"):
            try:
                _hasher.verify(self.password_hash, password)
            except (VerificationError, InvalidHashError):
                return False
            if _hasher.check_needs_rehash(self.password_hash):
                self.set_password(password)
            return True
        if check_password_hash(self.password_hash, password):
            self.set_password(password)
            return True
        return False

    def __repr__(self):
        return f"<User {self.username}>"
