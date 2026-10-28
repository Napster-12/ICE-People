"""Careers site and ATS (carried over from the original recruitment portal)."""
from app.extensions import db
from app.models.base import MappingMixin, TimestampMixin

APPLICATION_STATUSES = ["New", "Screening", "Shortlisted", "Interview", "Offer", "Hired", "Rejected"]
JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Learnership"]


class Job(MappingMixin, db.Model):
    __tablename__ = "jobs"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(120), index=True)
    location = db.Column(db.String(160))
    job_type = db.Column(db.String(40))
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.Text)
    preferred_skills = db.Column(db.Text)
    min_experience = db.Column(db.Integer, default=0)
    min_education = db.Column(db.Integer, default=0)
    closing_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), nullable=False, default="Open", index=True)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    requisition_id = db.Column(db.Integer, db.ForeignKey("requisitions.id"), index=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True)

    requisition = db.relationship("Requisition")
    applications = db.relationship("Application", back_populates="job", cascade="all, delete-orphan")


class Candidate(MappingMixin, TimestampMixin, db.Model):
    __tablename__ = "candidates"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(40))
    location = db.Column(db.String(160))
    current_title = db.Column(db.String(160))
    years_experience = db.Column(db.Integer)
    education_level = db.Column(db.Integer, default=0)
    skills = db.Column(db.Text)
    cv_file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id"))
    cv_text = db.Column(db.Text)
    consent = db.Column(db.Boolean, default=False, nullable=False)
    consent_at = db.Column(db.DateTime)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    cv_file = db.relationship("StoredFile")
    applications = db.relationship("Application", back_populates="candidate", cascade="all, delete-orphan")

    @property
    def cv_filename(self):
        return self.cv_file.original_name if self.cv_file else ""


class Application(MappingMixin, TimestampMixin, db.Model):
    __tablename__ = "applications"
    __table_args__ = (db.UniqueConstraint("candidate_id", "job_id"),
                      db.Index("idx_app_job_score", "job_id", "score"))
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    cover_note = db.Column(db.Text)
    score = db.Column(db.Float, default=0)
    breakdown = db.Column(db.JSON)
    status = db.Column(db.String(20), nullable=False, default="New", index=True)
    notes = db.Column(db.Text)
    source = db.Column(db.String(40), nullable=False, default="Applied")

    candidate = db.relationship(Candidate, back_populates="applications")
    job = db.relationship(Job, back_populates="applications")
