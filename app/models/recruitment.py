"""Careers site and ATS (carried over from the original recruitment portal), plus job adverts and the JD library
(spec §4.4). A Job is the advert: it's live on the careers site while its status is Open."""
from app.extensions import db
from app.models.base import MappingMixin, TimestampMixin
from app.services.dates import today

# "Not selected": shortlisted, but the Department Manager didn't pick them for interview (they get a regret).
APPLICATION_STATUSES = ["New", "Screening", "Shortlisted", "Not selected", "Interview", "Offer", "Hired", "Rejected"]
REVIEW_STATUSES = ["Pending", "Completed"]
MESSAGE_KINDS = {"invitation": "Interview invitation", "regret": "Regret"}
RECOMMENDATIONS = ["Appoint", "Possible", "Don't appoint"]
JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Learnership"]
ADVERT_STATUSES = ["Draft", "In Approval", "Returned", "Rejected", "Open", "Closed", "Cancelled"]


class JobDescriptionTemplate(TimestampMixin, db.Model):
    """The JD library: standard descriptions an advert starts from, reviewed every year."""
    __tablename__ = "jd_templates"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False, index=True)
    job_family_id = db.Column(db.Integer, db.ForeignKey("job_families.id"), index=True)
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.Text)
    preferred_skills = db.Column(db.Text)
    min_experience = db.Column(db.Integer, default=0, nullable=False)
    min_education = db.Column(db.Integer, default=0, nullable=False)
    ats_weights = db.Column(db.JSON)          # own ATS weights (ats.WEIGHT_LABELS keys, total 100); None = standard
    review_date = db.Column(db.Date, nullable=False, index=True)
    reminded_at = db.Column(db.DateTime)
    active = db.Column(db.Boolean, default=True, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    job_family = db.relationship("JobFamily")
    updated_by = db.relationship("User")

    @property
    def review_due(self):
        return self.review_date <= today()


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
    ats_weights = db.Column(db.JSON)          # copied from the JD when the advert is drafted; None = standard
    closing_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), nullable=False, default="Open", index=True)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    requisition_id = db.Column(db.Integer, db.ForeignKey("requisitions.id"), index=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True)

    # Advert fields (spec §4.4). Jobs imported from the old portal have no reference or requisition.
    reference = db.Column(db.String(20), unique=True, index=True)
    jd_template_id = db.Column(db.Integer, db.ForeignKey("jd_templates.id"), index=True)
    ee_statement = db.Column(db.Text)
    channels = db.Column(db.JSON)
    cycle = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    version = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    published_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    close_reason = db.Column(db.String(255))

    requisition = db.relationship("Requisition")
    jd_template = db.relationship(JobDescriptionTemplate)
    created_by = db.relationship("User")
    applications = db.relationship("Application", back_populates="job", cascade="all, delete-orphan")
    versions = db.relationship("AdvertVersion", back_populates="job", order_by="AdvertVersion.version.desc()",
                               cascade="all, delete-orphan")
    postings = db.relationship("AdvertPosting", back_populates="job",
                               order_by="AdvertPosting.id", cascade="all, delete-orphan")

    @property
    def is_advert(self):
        return self.reference is not None


class AdvertVersion(db.Model):
    """Snapshot of the advert each time a recruiter saves it."""
    __tablename__ = "advert_versions"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    cycle = db.Column(db.Integer, nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False)

    job = db.relationship(Job, back_populates="versions")
    created_by = db.relationship("User")


class AdvertPosting(db.Model):
    """One channel an advert went out on in one cycle, with its views and applications."""
    __tablename__ = "advert_postings"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    cycle = db.Column(db.Integer, nullable=False)
    channel = db.Column(db.String(40), nullable=False)
    external_id = db.Column(db.String(60))
    status = db.Column(db.String(20), nullable=False, default="Live")
    error = db.Column(db.String(255))
    published_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    views = db.Column(db.Integer, nullable=False, default=0)
    applications = db.Column(db.Integer, nullable=False, default=0)

    job = db.relationship(Job, back_populates="postings")


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
    messages = db.relationship("CandidateMessage", back_populates="application", cascade="all, delete-orphan",
                               order_by="CandidateMessage.sent_at.desc()")


class ShortlistReview(TimestampMixin, db.Model):
    """HR sends an advert's shortlist to the Department Manager, who picks who goes to interview (1 Nov 2026)."""
    __tablename__ = "shortlist_reviews"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    sent_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    application_ids = db.Column(db.JSON, nullable=False)      # the shortlist that was sent
    selected_ids = db.Column(db.JSON)                         # picked for interview
    status = db.Column(db.String(20), nullable=False, default="Pending", index=True)
    comment = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)

    job = db.relationship(Job)
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    sent_by = db.relationship("User", foreign_keys=[sent_by_id])

    @property
    def applications(self):
        ids = self.application_ids or []
        return Application.query.filter(Application.id.in_(ids)).order_by(Application.score.desc()).all() if ids else []


class InterviewPanel(TimestampMixin, db.Model):
    """One interview panel per advert (1 Nov 2026): the Department Manager plus managers HR invites. Every member
    scores every candidate on the advert's criteria."""
    __tablename__ = "interview_panels"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    criteria = db.Column(db.JSON, nullable=False)              # [{"name": ..., "weight": ...}], weights total 100
    invited_at = db.Column(db.DateTime)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    job = db.relationship(Job)
    invited_by = db.relationship("User")
    members = db.relationship("PanelMember", back_populates="panel", cascade="all, delete-orphan",
                              order_by="PanelMember.id")


class PanelMember(db.Model):
    __tablename__ = "panel_members"
    __table_args__ = (db.UniqueConstraint("panel_id", "user_id"),)
    id = db.Column(db.Integer, primary_key=True)
    panel_id = db.Column(db.Integer, db.ForeignKey("interview_panels.id", ondelete="CASCADE"), nullable=False,
                         index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(40), nullable=False, default="Panel member")   # or "Department Manager"
    invited_at = db.Column(db.DateTime)

    panel = db.relationship(InterviewPanel, back_populates="members")
    user = db.relationship("User")


class InterviewSlot(db.Model):
    """A candidate's interview: when and where, plus the calendar invite sent for it."""
    __tablename__ = "interview_slots"
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
                               unique=True)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    venue = db.Column(db.String(255), nullable=False)
    ics = db.Column(db.Text)

    application = db.relationship(Application, backref=db.backref("slot", uselist=False, cascade="all, delete-orphan"))


class Scorecard(db.Model):
    """One panellist's scores for one candidate (1–5 per criterion), with a comment and a recommendation."""
    __tablename__ = "scorecards"
    __table_args__ = (db.UniqueConstraint("application_id", "panellist_id"),)
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
                               index=True)
    panellist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    scores = db.Column(db.JSON, nullable=False)                 # {criterion name: 1..5}
    total = db.Column(db.Float, nullable=False)                 # weighted, 0–100
    comment = db.Column(db.Text)
    recommendation = db.Column(db.String(20), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False)

    application = db.relationship(Application, backref=db.backref("scorecards", cascade="all, delete-orphan"))
    panellist = db.relationship("User")


class CandidateMessage(db.Model):
    """An email HR sent an applicant (interview invitation or regret), kept on the application."""
    __tablename__ = "candidate_messages"
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
                               index=True)
    kind = db.Column(db.String(20), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    sent_at = db.Column(db.DateTime, nullable=False, index=True)

    application = db.relationship(Application, back_populates="messages")
    sent_by = db.relationship("User")
