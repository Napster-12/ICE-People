"""Travel requests (14 Nov 2026, at the user's request): the i-Travel travel request form, digitised.

A staff member fills in the form (client details, travellers, flights, accommodation and
auxiliary services). Their manager approves it (workflow type "travel"). On approval the form goes as a PDF to
i-Travel (the `itravel_email` setting) and Finance. i-Travel books it from the i-Travel dashboard, enters the cost and
attaches the quote or invoice, and sends it to Finance for a payment requisition (workflow type "travel_payment").
Finance approves the payment and marks it paid.
"""
import json

from app.extensions import db
from app.models.base import EncryptedString, TimestampMixin

TRAVEL_STATUSES = ["Draft", "In Approval", "Returned", "Rejected", "Approved", "With Finance", "Payment approved",
                   "Payment rejected", "Paid", "Cancelled"]
TRAVEL_EDITABLE = ("Draft", "Returned")                       # the requester can still change it
TRAVEL_CANCELLABLE = ("Draft", "Returned", "In Approval", "Approved")
TRAVEL_APPROVED = ("Approved", "With Finance", "Payment approved", "Payment rejected", "Paid")   # past the manager


class TravelRequest(TimestampMixin, db.Model):
    __tablename__ = "travel_requests"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)        # TRF-2026-00001
    status = db.Column(db.String(20), nullable=False, default="Draft", index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), index=True)

    # Client details (the requester, pre-filled from their profile).
    client_name = db.Column(db.String(160), nullable=False)
    client_address = db.Column(db.String(255))
    client_city = db.Column(db.String(120))
    client_zip = db.Column(db.String(20))
    client_phone = db.Column(db.String(40))
    client_email = db.Column(db.String(255))
    client_code = db.Column(db.String(60))
    # Travel booker details.
    booker_name = db.Column(db.String(160))
    booker_phone = db.Column(db.String(40))
    booker_email = db.Column(db.String(255))
    # Travel booking approver details: the manager who approved, kept as it was at approval.
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    approver_name = db.Column(db.String(160))
    approver_phone = db.Column(db.String(40))
    approver_email = db.Column(db.String(255))
    approved_at = db.Column(db.DateTime)

    # The form's tables, as JSON lists of rows. Travellers hold ID / passport numbers, so they're encrypted.
    travellers_json = db.Column(EncryptedString)
    flights_json = db.Column(db.Text)
    car_hire_json = db.Column(db.Text)            # unused since 14 Nov 2026 (car hire removed from the form)
    driver_details = db.Column(db.String(255))
    accommodation_json = db.Column(db.Text)
    auxiliary_json = db.Column(db.Text)

    form_file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id"))                  # the PDF as approved
    sent_to_itravel_at = db.Column(db.DateTime)

    # i-Travel's payment requisition to Finance.
    amount = db.Column(db.Numeric(14, 2))
    supplier_reference = db.Column(db.String(80))                                           # quote / invoice number
    payment_note = db.Column(db.Text)
    sent_to_finance_at = db.Column(db.DateTime)
    sent_to_finance_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    paid_on = db.Column(db.Date)
    payment_reference = db.Column(db.String(80))
    paid_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    requester = db.relationship("User", foreign_keys=[requester_id])
    approver = db.relationship("User", foreign_keys=[approver_id])
    sent_to_finance_by = db.relationship("User", foreign_keys=[sent_to_finance_by_id])
    paid_by = db.relationship("User", foreign_keys=[paid_by_id])
    department = db.relationship("Department")
    form_file = db.relationship("StoredFile", foreign_keys=[form_file_id])

    @staticmethod
    def _load(value):
        try:
            rows = json.loads(value) if value else []
        except (TypeError, ValueError):
            rows = []
        return rows if isinstance(rows, list) else []

    @property
    def travellers(self):
        return self._load(self.travellers_json)

    @property
    def flights(self):
        return self._load(self.flights_json)

    @property
    def car_hire(self):
        return self._load(self.car_hire_json)

    @property
    def accommodation(self):
        return self._load(self.accommodation_json)

    @property
    def auxiliary(self):
        return self._load(self.auxiliary_json)

    def rows(self, section):
        return getattr(self, section)

    @property
    def lead_traveller(self):
        t = self.travellers
        return f"{t[0].get('first_names', '')} {t[0].get('surname', '')}".strip() if t else self.client_name

    @property
    def first_date(self):
        """The earliest date on the trip (ISO text), for lists and sorting."""
        dates = [r.get("date") for r in self.flights] + [r.get("check_in") for r in self.accommodation]
        dates = [d for d in dates if d]
        return min(dates) if dates else None

    @property
    def summary(self):
        """"Durban → Johannesburg" for lists and email subjects (one traveller: the requester)."""
        if self.flights:
            f = self.flights[0]
            trip = f"{f.get('from', '')} → {f.get('to', '')}"
        elif self.accommodation:
            trip = f"Accommodation in {self.accommodation[0].get('locality', '')}"
        else:
            trip = "Auxiliary services"
        return trip
