"""Offers and onboarding (8 Nov 2026, at the user's request: HR Admin owns onboarding; part of spec Phases 7–8).

An Offer is made to a candidate the panel passed (Application status Offer). Above the requisition's costed CTC it
goes to Finance first. The candidate accepts or declines through a secure link; acceptance creates the Employee
(Pre-boarding) and the OnboardingCase. HR Admin generates the contract from a DocumentTemplate and uploads the signed
copy.
"""
from app.extensions import db
from app.models.base import EncryptedString, TimestampMixin

SALUTATIONS = ["Mr", "Ms", "Mrs", "Dr", "Prof"]
OFFER_STATUSES = ["Draft", "In Approval", "Returned", "Rejected", "Approved", "Sent", "Accepted", "Declined",
                  "Expired", "Withdrawn"]
OFFER_EDITABLE = ("Draft", "Returned")
OFFER_OPEN = ("Draft", "In Approval", "Returned", "Approved", "Sent")       # still in play
CASE_STATUSES = ["Pre-boarding", "Cancelled"]
CONTRACT_STATUSES = ["Awaiting contract", "Signed"]   # 10 Nov 2026: attached by the HR BP, not generated


class Offer(TimestampMixin, db.Model):
    __tablename__ = "offers"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)       # OFR-2026-00001
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Draft", index=True)
    ctc = db.Column(db.Numeric(14, 2), nullable=False)                                   # annual cost to company
    start_date = db.Column(db.Date, nullable=False)
    employment_type = db.Column(db.String(20), nullable=False)
    contract_end_date = db.Column(db.Date)
    conditions = db.Column(db.Text)
    # For the letter, as in Icebolethu's current offer letter (8 Nov 2026).
    salutation = db.Column(db.String(10))                                                # Mr, Ms, Mrs, Dr, Prof
    candidate_address = db.Column(db.Text)
    work_location = db.Column(db.String(255))                                            # "You will be based at"
    probation_months = db.Column(db.Integer)
    accepted_file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id"))            # the letter as accepted
    expires_on = db.Column(db.Date, nullable=False)                                      # last day to accept
    needs_approval = db.Column(db.Boolean, nullable=False, default=False)                 # above the costed CTC
    token = db.Column(db.String(64), unique=True, index=True)                            # the candidate's link
    sent_at = db.Column(db.DateTime)
    responded_at = db.Column(db.DateTime)
    response_ip = db.Column(db.String(64))
    decline_reason = db.Column(db.Text)
    code_of_conduct_at = db.Column(db.DateTime)          # the candidate accepted the Code of Conduct (16 Nov 2026)
    letter_file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id"))              # the PDF as sent
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    application = db.relationship("Application", backref=db.backref("offers", order_by="Offer.id"))
    letter_file = db.relationship("StoredFile", foreign_keys=[letter_file_id])
    accepted_file = db.relationship("StoredFile", foreign_keys=[accepted_file_id])
    created_by = db.relationship("User")

    @property
    def candidate(self):
        return self.application.candidate

    @property
    def job(self):
        return self.application.job

    @property
    def requisition(self):
        return self.application.job.requisition if self.application.job else None


class OnboardingCase(TimestampMixin, db.Model):
    __tablename__ = "onboarding_cases"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)       # ONB-2026-00001
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), index=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offers.id"), index=True)
    start_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Pre-boarding", index=True)
    contract_status = db.Column(db.String(20), nullable=False, default="Awaiting contract")
    contract_signed_on = db.Column(db.Date)

    employee = db.relationship("Employee", backref=db.backref("onboarding_cases", order_by="OnboardingCase.id"))
    application = db.relationship("Application")
    offer = db.relationship(Offer, backref=db.backref("onboarding_case", uselist=False))


SCREENING_STATUSES = ["Awaiting consent", "Consent refused", "In progress", "Clear", "Adverse"]
CHECK_STATUSES = ["Pending", "Clear", "Adverse"]


class BackgroundScreening(TimestampMixin, db.Model):
    """Background checks on a candidate who passed the interview, before the offer is sent (16 Nov 2026, at the
    user's request; spec IN-008). One per application. The candidate consents online (POPIA) through a secure link;
    HR Admin or the department's HR Business Partner records each check's result. The offer can only be sent once
    every check is Clear."""
    __tablename__ = "background_screenings"
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
                               unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="Awaiting consent", index=True)
    token = db.Column(db.String(64), unique=True, index=True)                # the candidate's consent link
    consent_requested_at = db.Column(db.DateTime)
    consent_at = db.Column(db.DateTime)                                      # given or refused
    consent_name = db.Column(db.String(160))                                 # the name the candidate typed
    consent_id_number = db.Column(EncryptedString)                           # on the POPIA consent (16 Nov 2026)
    consent_place = db.Column(db.String(120))                                # "Signed at"
    consent_ip = db.Column(db.String(64))
    completed_at = db.Column(db.DateTime)                                    # every check Clear, or one Adverse
    started_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    application = db.relationship("Application", backref=db.backref("screening", uselist=False,
                                                                    cascade="all, delete-orphan"))
    started_by = db.relationship("User")
    checks = db.relationship("BackgroundCheck", back_populates="screening", cascade="all, delete-orphan",
                             order_by="BackgroundCheck.id")


class BackgroundCheck(TimestampMixin, db.Model):
    """One check (from the "background_checks" setting) and its result. The provider's report is a StoredFile
    (entity type "background_check"); the latest upload is current."""
    __tablename__ = "background_checks"
    id = db.Column(db.Integer, primary_key=True)
    screening_id = db.Column(db.Integer, db.ForeignKey("background_screenings.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    provider_reference = db.Column(db.String(80))
    completed_on = db.Column(db.Date)
    notes = db.Column(db.Text)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime)

    screening = db.relationship(BackgroundScreening, back_populates="checks")
    recorded_by = db.relationship("User")


PACK_STATUSES = ["Not started", "In progress", "Submitted", "Returned", "Approved"]


class NewStarterPack(TimestampMixin, db.Model):
    """The new starter pack (16 Nov 2026, at the user's request): on acceptance the candidate gets a secure link to
    fill in the New Hire Take-On form online and upload the Business and Financial Disclosure and the Liberty
    nomination of beneficiary. The department's HR Business Partner reviews it; approval updates the employee
    record."""
    __tablename__ = "new_starter_packs"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("onboarding_cases.id", ondelete="CASCADE"), nullable=False,
                        unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="Not started", index=True)
    token = db.Column(db.String(64), unique=True, index=True)
    data = db.Column(EncryptedString)                     # the Take-On form's answers, JSON (ID, bank details...)
    uploads = db.Column(db.JSON)                          # {document key: StoredFile id}
    declared_name = db.Column(db.String(160))
    submitted_at = db.Column(db.DateTime)
    submitted_ip = db.Column(db.String(64))
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    review_comment = db.Column(db.Text)

    case = db.relationship(OnboardingCase, backref=db.backref("pack", uselist=False, cascade="all, delete-orphan"))
    reviewed_by = db.relationship("User")


class DocumentTemplate(TimestampMixin, db.Model):
    """Editable wording for the offer letter (HR Admin). The body is text with {{ placeholders }};
    blank lines make paragraphs, "Label: value" lines a details table and "- " lines bullets, as in the emails."""
    __tablename__ = "document_templates"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    updated_by = db.relationship("User")
