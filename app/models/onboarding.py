"""Offers and onboarding (8 Nov 2026, at the user's request: HR Admin owns onboarding; part of spec Phases 7–8).

An Offer is made to a candidate the panel passed (Application status Offer). Above the requisition's costed CTC it
goes to Finance first. The candidate accepts or declines through a secure link; acceptance creates the Employee
(Pre-boarding) and the OnboardingCase. HR Admin generates the contract from a DocumentTemplate and uploads the signed
copy.
"""
from app.extensions import db
from app.models.base import TimestampMixin

SALUTATIONS = ["Mr", "Ms", "Mrs", "Dr", "Prof"]
OFFER_STATUSES = ["Draft", "In Approval", "Returned", "Rejected", "Approved", "Sent", "Accepted", "Declined",
                  "Expired", "Withdrawn"]
OFFER_EDITABLE = ("Draft", "Returned")
OFFER_OPEN = ("Draft", "In Approval", "Returned", "Approved", "Sent")       # still in play
CASE_STATUSES = ["Pre-boarding", "Cancelled"]
CONTRACT_STATUSES = ["Not generated", "Generated", "Signed"]


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
    contract_status = db.Column(db.String(20), nullable=False, default="Not generated")
    contract_generated_at = db.Column(db.DateTime)
    contract_signed_on = db.Column(db.Date)

    employee = db.relationship("Employee", backref=db.backref("onboarding_cases", order_by="OnboardingCase.id"))
    application = db.relationship("Application")
    offer = db.relationship(Offer, backref=db.backref("onboarding_case", uselist=False))


class DocumentTemplate(TimestampMixin, db.Model):
    """Editable wording for the offer letter and the contracts (HR Admin). The body is text with {{ placeholders }};
    blank lines make paragraphs, "Label: value" lines a details table and "- " lines bullets, as in the emails."""
    __tablename__ = "document_templates"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    updated_by = db.relationship("User")
