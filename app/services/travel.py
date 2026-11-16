"""Travel requests (14 Nov 2026, at the user's request): the i-Travel travel request form, digitised.

1. Any staff member raises their own trip (they are the client, booker and traveller, from their account and employee
   record) and fills in flights,
   transfers, accommodation and auxiliary services. It can be saved as a draft.
2. Submitting sends it to the requester's manager (workflow type "travel"; the only approver).
3. On approval the form is kept as a PDF and emailed to i-Travel (the `itravel_email` setting) and Finance; the
   i-Travel role and Finance are notified in the system.
4. i-Travel books it from the i-Travel dashboard, enters the cost and attaches the quote or invoice, and sends it to
   Finance as a payment requisition (workflow type "travel_payment").
5. Finance approves the payment (returning it sends it back to i-Travel) and marks it paid.
"""
import io
import json
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import current_app

from app.extensions import db
from app.integrations import IntegrationError, get_adapter
from app.models import TravelRequest, WorkflowInstance, WorkflowStep
from app.models.travel import TRAVEL_APPROVED, TRAVEL_CANCELLABLE, TRAVEL_EDITABLE
from app.models.user import FINANCE, ITRAVEL
from app.services import audit, documents, files, refs, settings, workflow
from app.services.dates import format_date, format_money, now, today
from app.services.errors import DomainError
from app.services.notifications import notify, render, users_with_role

FORM_FILE = "travel_form"              # the PDF as approved
INVOICE_FILE = "travel_invoice"        # i-Travel's quote or invoice, attached for Finance
INVOICE_TYPES = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"}
ENTITY = "travel_request"              # the manager's approval
PAYMENT_ENTITY = "travel_payment"      # Finance's payment approval

# i-Travel's details, as at the top of their form.
ITRAVEL_OFFICE = {"address": "387 Surrey Avenue, Ferndale", "city": "Randburg, Johannesburg", "country": "South Africa",
                  "zip": "2194", "phone": "087 077 5590", "email": "quotes@i-travel.africa",
                  "web": "www.i-travel.africa", "after_hours": "064 860 5829"}

GENDERS = ["Male (M)", "Female (F)"]
SEATS = ["Window", "Aisle", "Middle", "Front of the aircraft", "Exit row (extra legroom)", "No preference"]
AIRLINES = ["FlySafair", "SAA", "Airlink", "Emirates"]   # 14 Nov 2026, at the user's request
FLIGHT_CLASSES = ["Standard Economy", "Premium Economy", "Business", "First"]
STAY_SERVICES = ["Bed only", "Bed/Breakfast", "Dinner/Bed/Breakfast", "Full board"]

# The form's tables: section -> (title, max rows, [(key, label, kind, required, options)]).
# kind: text, email, date, time, number or select. Dates are kept as ISO text.
# The traveller (14 Nov 2026, at the user's request): every staff member raises their own trip, so there's no
# travellers table to fill in. The traveller is the requester, taken from their account and employee record
# (`traveller_for`) and kept on the request; the detail page and the PDF show it in i-Travel's traveller table.
TRAVELLER_TITLE = "Detail of traveller as it appears on the ID / passport document"
TRAVELLER_FIELDS = [("first_names", "Full name(s)"), ("surname", "Surname"), ("gender", "Gender (M/F)"),
                    ("citizenship", "Citizenship"), ("id_number", "ID / Passport #"), ("phone", "Telephone"),
                    ("email", "Email address"), ("seat", "Seat preference")]
# One traveller, so "No. of PAX" is always 1: not asked, shown as 1 on the PDF.
SECTIONS = {
    "flights": ("Flight details", 5, [
        ("date", "Outbound date", "date", True, None),
        ("from", "From", "text", True, None),
        ("to", "To", "text", True, None),
        ("earliest", "Earliest time", "time", False, None),
        ("latest", "Latest time", "time", False, None),
        ("class", "Class description", "select", False, FLIGHT_CLASSES),
        ("airline", "Preferred airline", "select", False, AIRLINES),
        ("special", "Special service", "text", False, None),
    ]),
    "accommodation": ("Accommodation", 3, [
        ("service", "Service type", "select", True, STAY_SERVICES),
        ("check_in", "Check-in date", "date", True, None),
        ("check_out", "Check-out date", "date", True, None),
        ("room_type", "Room type", "text", False, None),
        ("locality", "Locality", "text", True, None),
        ("vendor", "Preferred vendor", "text", False, None),
        ("special", "Special requirement", "text", False, None),
    ]),
    "auxiliary": ("Auxiliary services", 3, [
        ("service", "Service type", "text", True, None),
        ("description", "Service description", "text", True, None),
        ("quantity", "Quantity", "number", False, None),
        ("special", "Special requirement", "text", False, None),
    ]),
}
ROW_NAMES = {"flights": "Flight", "accommodation": "Accommodation", "auxiliary": "Auxiliary service"}
TRIP_SECTIONS = ("flights", "accommodation", "auxiliary")   # car hire / transfers removed 14 Nov 2026

# i-Travel's notes under each section of the form.
NOTES = {
    "flights": [
        "Cut-off time for submission of normal flight bookings and reservation changes: domestic 2 hrs 30 min; "
        "regional 24 hrs; international 48 hrs before departure.",
        "All flight reservations are valid at the time of quotation only, and any airline changes are subject to "
        "seat availability and/or the airline's terms and conditions.",
        "It is the responsibility of the individual(s) travelling to check in at the airport 2 hours before "
        "departure, as directed by ACSA and/or the airline's terms and conditions.",
        "A R500.00 admin fee (incl. taxes and airport charges) will be charged by SAA when refunding tickets "
        "(fee subject to change).",
    ],
    "accommodation": [
        "All accommodation reservations are valid at the time of quotation only, and any request changes are subject "
        "to availability and/or the vendor's terms and conditions.",
        "Booking cancellation is subject to the vendor's cancellation policy and/or terms and conditions.",
        "A no-show will be charged partially or in full.",
    ],
    "auxiliary": [
        "All service reservations are valid at the time of quotation only, and any request changes are subject to "
        "availability and/or the vendor's terms and conditions.",
    ],
}

# The client and the travel booker are the signed-in requester (14 Nov 2026, at the user's request: the portal knows
# who they are), filled in from their account and employee record, not typed. Only the driver details are typed.
CLIENT_FIELDS = []   # 14 Nov 2026: nothing typed about the client; driver details went with car hire
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


# ------------------------------------------------------------------ who sees what

def can_view(user, tr):
    if tr.requester_id == user.id or user.has_role(ITRAVEL):
        return True
    if user.has_role(FINANCE) and tr.status in TRAVEL_APPROVED:
        return True
    return _is_approver(user, tr)


def _is_approver(user, tr):
    """Anyone with a step on the request's approvals (the manager, a delegate, Finance)."""
    return (WorkflowStep.query.join(WorkflowInstance)
            .filter(WorkflowInstance.entity_type.in_((ENTITY, PAYMENT_ENTITY)), WorkflowInstance.entity_id == tr.id,
                    db.or_(WorkflowStep.approver_id == user.id, WorkflowStep.assignee_id == user.id,
                           WorkflowStep.actor_id == user.id))
            .first()) is not None


def can_see_ids(user, tr):
    """Full ID / passport numbers: the requester and i-Travel (who books). Others see the last four digits."""
    return tr.requester_id == user.id or user.has_role(ITRAVEL)


def mask(value):
    value = value or ""
    return ("•" * max(len(value) - 4, 0)) + value[-4:] if len(value) > 4 else value


def can_edit(user, tr):
    return tr.requester_id == user.id and tr.status in TRAVEL_EDITABLE


def can_cancel(user, tr):
    return tr.requester_id == user.id and tr.status in TRAVEL_CANCELLABLE


def can_send_to_finance(user, tr):
    return user.has_role(ITRAVEL) and tr.status == "Approved"


def can_mark_paid(user, tr):
    return user.has_role(FINANCE) and tr.status == "Payment approved"


def mine(user):
    return TravelRequest.query.filter_by(requester_id=user.id).order_by(TravelRequest.created_at.desc()).all()


def by_status(*statuses):
    return (TravelRequest.query.filter(TravelRequest.status.in_(statuses))
            .order_by(TravelRequest.approved_at.desc(), TravelRequest.id.desc()).all())


# ------------------------------------------------------------------ the form

def profile(user):
    """The requester as client and travel booker, from their account and employee record."""
    emp = user.employee
    phone = (emp.phone if emp else None) or None
    email = user.email or (emp.email if emp else None) or None
    return {"client_name": user.full_name, "client_phone": phone, "client_email": email,
            "booker_name": user.full_name, "booker_phone": phone, "booker_email": email}


CITIZENSHIP = {"0": "South Africa", "1": "South Africa (permanent resident)"}


def traveller_for(user, seat=None):
    """The requester as the traveller. Named as on their account ("Tinashe Chadamoyo" → full names "Tinashe",
    surname "Chadamoyo"), not the employee record's names: on renamed accounts those can still be the placeholder the
    account was created with ("ICT" / "Department Manager"). ID number, gender and phone come from the employee
    record; citizenship from the SA ID number's citizenship digit."""
    emp, who = user.employee, profile(user)
    parts = (user.full_name or "").split()
    first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (" ".join(parts), "")
    id_number = ((emp.id_number if emp else None) or "").strip()
    gender = (emp.gender if emp else None) or ""
    citizenship = CITIZENSHIP.get(id_number[10:11], "") if re.fullmatch(r"\d{13}", id_number) else ""
    return {"first_names": first, "surname": last,
            "gender": {"Male": "Male (M)", "Female": "Female (F)"}.get(gender, gender),
            "citizenship": citizenship, "id_number": id_number, "phone": who["client_phone"] or "",
            "email": who["client_email"] or "", "seat": seat if seat in SEATS else ""}


def traveller_problems(user):
    """What's missing from the requester's employee record to book a trip (checked on submitting)."""
    emp = user.employee
    missing = [label for value, label in (((emp.id_number if emp else None), "ID number"),
                                          ((emp.phone if emp else None), "phone number"))
               if not (value or "").strip()]
    if not missing:
        return []
    one = len(missing) == 1
    return [f"Your {' and '.join(missing)} {'is' if one else 'are'} not on your employee record yet. Ask HR to add "
            f"{'it' if one else 'them'}, then submit again."]


def defaults_for(user):
    """A new request: nothing to fill in about the traveller (it's the requester)."""
    return {"seat": ""}


def values_of(tr):
    """A saved request as form values."""
    out = {key: getattr(tr, key) or "" for key, _label, _max in CLIENT_FIELDS}
    out["seat"] = tr.travellers[0].get("seat", "") if tr.travellers else ""
    for section in SECTIONS:
        out[section] = tr.rows(section)
    return out


def _parse_date(raw):
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _rows(form, section):
    """The section's rows from the form (fields named <section>.<key>, one value per row); blank rows dropped."""
    _title, max_rows, fields = SECTIONS[section]
    columns = {key: form.getlist(f"{section}.{key}") for key, *_ in fields}
    count = min(max((len(v) for v in columns.values()), default=0), max_rows)
    rows = []
    for i in range(count):
        row = {key: " ".join(str(columns[key][i] if i < len(columns[key]) else "").split())[:255]
               for key, *_ in fields}
        if any(row.values()):
            rows.append(row)
    return rows


def _check_row(section, n, row, strict):
    """Errors for one row ("Flight 2: enter the outbound date.")."""
    _title, _max, fields = SECTIONS[section]
    name, errors = f"{ROW_NAMES[section]} {n}", []
    for key, label, kind, required, options in fields:
        value = row.get(key, "")
        if not value:
            if required and strict:
                errors.append(f"{name}: enter the {label.lower()}.")
            continue
        if kind == "select" and value not in options:
            errors.append(f"{name}: choose the {label.lower()} from the list.")
        elif kind == "date" and _parse_date(value) is None:
            errors.append(f"{name}: enter the {label.lower()} as a date.")
        elif kind == "date" and strict and _parse_date(value) < today():
            errors.append(f"{name}: the {label.lower()} ({format_date(_parse_date(value))}) can't be in the past.")
        elif kind == "time" and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            errors.append(f"{name}: enter the {label.lower()} as a time, e.g. 07:00.")
        elif kind == "number" and not (value.isdigit() and 1 <= int(value) <= 99):
            errors.append(f"{name}: the {label.lower()} must be a whole number from 1 to 99.")
        elif kind == "email" and not _EMAIL.fullmatch(value):
            errors.append(f"{name}: enter a valid email address.")
    if section == "flights" and row.get("earliest") and row.get("latest") and row["latest"] < row["earliest"]:
        errors.append(f"{name}: the latest time can't be before the earliest time.")
    if section == "accommodation":
        start, end = _parse_date(row.get("check_in")), _parse_date(row.get("check_out"))
        if start and end:
            if end <= start:
                errors.append(f"{name}: check-out ({format_date(end)}) must be after check-in ({format_date(start)}).")
            else:
                row["nights"] = str((end - start).days)
    return errors


def parse(form, strict):
    """Form values → clean fields, or DomainError. strict (submitting) also needs every required value and a trip;
    a draft can be incomplete."""
    out, errors = {}, []
    for key, label, max_len in CLIENT_FIELDS:
        out[key] = " ".join((form.get(key) or "").split())[:max_len] or None
    out["seat"] = (form.get("seat") or "").strip()
    if out["seat"] and out["seat"] not in SEATS:
        errors.append("Choose the seat preference from the list.")
    for section in SECTIONS:
        rows = _rows(form, section)
        for n, row in enumerate(rows, 1):
            errors += _check_row(section, n, row, strict)
        out[section] = rows
    if strict:
        if not any(out[s] for s in TRIP_SECTIONS):
            errors.append("Add at least one flight, accommodation or auxiliary service.")
    if errors:
        raise DomainError(" ".join(errors))
    return out


def _apply(tr, clean, user):
    for key, _label, _max in CLIENT_FIELDS:
        setattr(tr, key, clean[key])
    for key, value in profile(user).items():           # the requester is the client and the booker
        setattr(tr, key, value)
    tr.travellers_json = json.dumps([traveller_for(user, clean["seat"])])   # the requester travels
    tr.flights_json = json.dumps(clean["flights"])
    tr.accommodation_json = json.dumps(clean["accommodation"])
    tr.auxiliary_json = json.dumps(clean["auxiliary"])


def create(user, form, submit_now=False):
    clean = parse(form, strict=submit_now)
    emp = user.employee
    tr = TravelRequest(reference=refs.next_reference("TRF"), status="Draft", requester_id=user.id,
                       department_id=emp.department_id if emp else None)
    _apply(tr, clean, user)
    db.session.add(tr)
    db.session.flush()
    audit.record("create", "travel_request", tr.id, after={"ref": tr.reference}, user=user)
    if submit_now:
        submit(tr, user)
    return tr


def save(tr, user, form, submit_now=False):
    if not can_edit(user, tr):
        raise DomainError(f"A {tr.status.lower()} travel request can't be changed.")
    clean = parse(form, strict=submit_now)
    _apply(tr, clean, user)
    audit.record("update", "travel_request", tr.id, after={"ref": tr.reference}, user=user)
    if submit_now:
        submit(tr, user)
    return tr


def submit(tr, user):
    """To the requester's manager (workflow type "travel")."""
    if tr.requester_id != user.id or tr.status not in TRAVEL_EDITABLE:
        raise DomainError(f"A {tr.status.lower()} travel request can't be submitted.")
    parse(_as_form(tr), strict=True)                  # everything required is there
    problems = traveller_problems(user)
    if problems:
        raise DomainError(" ".join(problems))
    tr.travellers_json = json.dumps([traveller_for(user, values_of(tr)["seat"])])   # as on the record now
    old = tr.status
    tr.status = "In Approval"
    audit.record("status_change", "travel_request", tr.id, before={"status": old}, after={"status": "In Approval"},
                 user=user)
    workflow.start("travel", ENTITY, tr.id, user, context={"department_id": tr.department_id,
                                                          "travellers": 1},
                   department=tr.department)


def _as_form(tr):
    """A saved request as a MultiDict, to check it again with parse()."""
    from werkzeug.datastructures import MultiDict
    pairs = [(key, getattr(tr, key) or "") for key, _label, _max in CLIENT_FIELDS]
    pairs.append(("seat", values_of(tr)["seat"]))
    for section, (_title, _max, fields) in SECTIONS.items():
        for row in tr.rows(section):
            pairs += [(f"{section}.{key}", row.get(key, "")) for key, *_ in fields]
    return MultiDict(pairs)


def cancel(tr, user, reason=""):
    if not can_cancel(user, tr):
        raise DomainError(f"A {tr.status.lower()} travel request can't be cancelled.")
    workflow.cancel(workflow.latest_instance(ENTITY, tr.id))
    old = tr.status
    tr.status = "Cancelled"
    audit.record("status_change", "travel_request", tr.id, before={"status": old}, after={"status": "Cancelled"},
                 detail=(reason or "").strip()[:500] or None, user=user)
    if old == "Approved":                                  # i-Travel already has it: tell them
        _tell(users_with_role(ITRAVEL), tr, "Cancelled", f"{tr.requester.full_name} cancelled travel request "
              f"{tr.reference} after it was approved. Please cancel any bookings made for it."
              + (f"\n\nReason: {reason.strip()}" if (reason or "").strip() else ""))


# ------------------------------------------------------------------ display

def show(kind, value):
    """A stored value for screens and the PDF: dates as "11 Nov 2026"."""
    if kind == "date" and value:
        d = _parse_date(value)
        return format_date(d) if d else value
    return value or ""


def context_for(tr):
    return {"ref": tr.reference, "traveller": tr.lead_traveller, "trip": tr.summary,
            "requester": tr.requester.full_name, "department": tr.department.name if tr.department else "",
            "first_date": show("date", tr.first_date) or "", "approver": tr.approver_name or "",
            "approved_on": documents.long_datetime(tr.approved_at) if tr.approved_at else ""}


def form_pdf(tr):
    """The completed form as PDF bytes, laid out like i-Travel's travel request form."""
    from xhtml2pdf import pisa
    html = current_app.jinja_env.get_template("documents/travel_form.html").render(
        tr=tr, sections=SECTIONS, notes=NOTES, office=ITRAVEL_OFFICE, show=show, traveller_title=TRAVELLER_TITLE,
        traveller_fields=TRAVELLER_FIELDS, traveller=tr.travellers[0] if tr.travellers else traveller_for(tr.requester),
        logo=os.path.join(documents.STATIC, "logo.png"), approved_on=documents.long_datetime(tr.approved_at)
        if tr.approved_at else "", today=documents.long_date(today()))
    out = io.BytesIO()
    result = pisa.CreatePDF(html, dest=out, encoding="utf-8")
    if result.err:
        raise DomainError("The travel request PDF couldn't be made.")
    return out.getvalue()


def pdf_name(tr):
    return f"{tr.reference} travel request.pdf"


def _link(tr):
    return f"/travel/{tr.id}"


def _tell(users, tr, status, message, email=True):
    notify(users, "travel_status", link=_link(tr), email=email, ref=tr.reference, status=status, message=message,
           traveller=tr.lead_traveller, trip=tr.summary)


# ------------------------------------------------------------------ after the manager approves

def itravel_email_live():
    try:
        return settings.get("itravel_email_live", float) >= 1
    except ValueError:
        return False


def _send_booking(tr, pdf):
    """Email the approved form to i-Travel and to Finance, with the PDF attached. A failure is logged only (it's in
    the Integration Log); the approval stands."""
    finance = users_with_role(FINANCE)
    # i-Travel's real address only when switched on (itravel_email_live; off until i-Travel goes live, 15 Nov 2026).
    itravel = [settings.get("itravel_email")] if itravel_email_live() else []
    addresses = itravel + [u.email for u in finance if u.email]
    context = context_for(tr)
    subject, body = render("travel_booking", context)
    from app.services.emails import designed
    html = designed("travel_booking", subject, body, _link(tr), context)
    sent = []
    for address in dict.fromkeys(a.strip() for a in addresses if a and a.strip()):
        try:
            get_adapter("email").send_email(address, subject, body, html=html,
                                            attachments=[(pdf_name(tr), pdf, "application/pdf")])
            sent.append(address)
        except IntegrationError as exc:
            current_app.logger.error("Travel request %s to %s failed: %s", tr.reference, address, exc)
    tr.sent_to_itravel_at = now()
    audit.record("travel.sent", "travel_request", tr.id, after={"to": sent})
    # In the system: Finance and the i-Travel role (no second email: Finance has just had it).
    _tell(finance, tr, "Approved", f"{tr.approver_name} approved travel request {tr.reference} from "
          f"{tr.requester.full_name}. i-Travel will book it and send the payment requisition.", email=False)
    _tell(users_with_role(ITRAVEL), tr, "Approved", f"{tr.approver_name} approved travel request {tr.reference} from "
          f"{tr.requester.full_name}. Please book it, then send the quote or invoice to Finance from the i-Travel "
          "dashboard.", email=False)


def _travel(instance):
    return db.session.get(TravelRequest, instance.entity_id)


def _on_approved(instance):
    tr = _travel(instance)
    step = next((s for s in reversed(instance.steps) if s.status == "Approved" and s.actor_id), None)
    approver = step.actor if step else None
    if approver is not None:
        emp = approver.employee
        tr.approver_id, tr.approver_name = approver.id, approver.full_name
        tr.approver_email = approver.email or (emp.email if emp else None)
        tr.approver_phone = emp.phone if emp else None
    tr.approved_at = now()
    tr.status = "Approved"
    audit.record("status_change", "travel_request", tr.id, before={"status": "In Approval"},
                 after={"status": "Approved"})
    pdf = form_pdf(tr)
    tr.form_file = files.store_bytes(pdf, pdf_name(tr), FORM_FILE, tr.id, check=False)
    _send_booking(tr, pdf)
    _tell(tr.requester, tr, "Approved", f"{tr.approver_name or 'Your manager'} approved your travel request. It has "
          "been sent to i-Travel to book, and to Finance.")


def _on_returned(instance):
    _travel(instance).status = "Returned"            # the workflow tells the requester why


def _on_rejected(instance):
    _travel(instance).status = "Rejected"


def _describe(instance):
    tr = _travel(instance)
    if tr is None:
        return {"ref": f"Travel #{instance.entity_id}", "title": "", "link": None}
    prefix = "Travel payment" if instance.workflow_type == "travel_payment" else "Travel"
    title = f"{prefix}: {tr.lead_traveller}, {tr.summary}"
    if instance.workflow_type == "travel_payment" and tr.amount is not None:
        title += f" · {format_money(tr.amount)}"
    return {"ref": tr.reference, "title": title, "link": _link(tr)}


# ------------------------------------------------------------------ i-Travel → Finance

def parse_amount(raw):
    try:
        amount = Decimal(str(raw or "").replace(" ", "").replace(",", "").replace("R", "") or "x")
        if amount <= 0:
            raise InvalidOperation
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise DomainError("Enter the total cost as an amount, e.g. 8450.00.") from None


def send_to_finance(tr, user, amount, supplier_reference, note, upload):
    """i-Travel has booked it: the payment requisition goes to Finance with the quote or invoice."""
    if not can_send_to_finance(user, tr):
        raise DomainError("Only i-Travel can send an approved travel request to Finance.")
    amount = parse_amount(amount)
    supplier_reference = " ".join((supplier_reference or "").split())[:80]
    if not supplier_reference:
        raise DomainError("Enter the quote or invoice number.")
    if upload is None or not upload.filename:
        raise DomainError("Attach the quote or invoice.")
    stored = files.save_upload(upload, INVOICE_FILE, tr.id, user=user, allowed=INVOICE_TYPES)
    tr.amount, tr.supplier_reference = amount, supplier_reference
    tr.payment_note = (note or "").strip()[:2000] or None
    tr.sent_to_finance_at, tr.sent_to_finance_by_id = now(), user.id
    tr.status = "With Finance"
    audit.record("status_change", "travel_request", tr.id, before={"status": "Approved"},
                 after={"status": "With Finance", "amount": str(amount), "invoice": stored.original_name}, user=user)
    workflow.start("travel_payment", PAYMENT_ENTITY, tr.id, user,
                   context={"department_id": tr.department_id, "amount": float(amount)}, department=tr.department)


def invoices(tr):
    """Newest first: the first is the current quote or invoice."""
    return list(reversed(files.files_for(INVOICE_FILE, tr.id)))


def _payment_approved(instance):
    tr = _travel(instance)
    tr.status = "Payment approved"
    audit.record("status_change", "travel_request", tr.id, before={"status": "With Finance"},
                 after={"status": "Payment approved"})
    if tr.sent_to_finance_by is not None:
        _tell(tr.sent_to_finance_by, tr, "Payment approved", f"Finance approved the payment of "
              f"{format_money(tr.amount)} for travel request {tr.reference}.")


def _payment_returned(instance):
    """Back to i-Travel to correct and send again (the workflow tells them why)."""
    _travel(instance).status = "Approved"


def _payment_rejected(instance):
    tr = _travel(instance)
    tr.status = "Payment rejected"
    _tell(tr.requester, tr, "Payment rejected", f"Finance rejected the payment for your travel request "
          f"{tr.reference}. Please speak to Finance.")


def mark_paid(tr, user, paid_on, payment_reference):
    if not can_mark_paid(user, tr):
        raise DomainError("Only Finance can mark an approved payment as paid.")
    if paid_on is None:
        raise DomainError("Enter the date it was paid.")
    if paid_on > today():
        raise DomainError("The payment date can't be in the future.")
    payment_reference = " ".join((payment_reference or "").split())[:80]
    if not payment_reference:
        raise DomainError("Enter the payment reference.")
    tr.paid_on, tr.payment_reference, tr.paid_by_id, tr.status = paid_on, payment_reference, user.id, "Paid"
    audit.record("status_change", "travel_request", tr.id, before={"status": "Payment approved"},
                 after={"status": "Paid", "payment_reference": payment_reference}, user=user)
    users = [tr.requester] + ([tr.sent_to_finance_by] if tr.sent_to_finance_by else [])
    _tell(users, tr, "Paid", f"Finance paid {format_money(tr.amount)} for travel request {tr.reference} on "
          f"{format_date(paid_on)} (payment reference {payment_reference}).")


# ------------------------------------------------------------------ the i-Travel dashboard

DASHBOARD_TABS = [("to_book", "To book", ("Approved",)), ("finance", "With Finance", ("With Finance",)),
                  ("to_pay", "Payment approved", ("Payment approved",)), ("paid", "Paid", ("Paid",)),
                  ("rejected", "Payment rejected", ("Payment rejected",))]


def dashboard():
    counts = dict(db.session.query(TravelRequest.status, db.func.count()).group_by(TravelRequest.status).all())
    month_start = today().replace(day=1)
    paid_month = (db.session.query(db.func.coalesce(db.func.sum(TravelRequest.amount), 0))
                  .filter(TravelRequest.status == "Paid", TravelRequest.paid_on >= month_start).scalar())
    awaiting = (db.session.query(db.func.coalesce(db.func.sum(TravelRequest.amount), 0))
                .filter(TravelRequest.status.in_(("With Finance", "Payment approved"))).scalar())
    return {"counts": counts, "paid_month": Decimal(paid_month or 0), "awaiting": Decimal(awaiting or 0)}


workflow.register("travel", describe=_describe, on_approved=_on_approved, on_returned=_on_returned,
                  on_rejected=_on_rejected, sample_context={"department_id": 1, "travellers": 1})
workflow.register("travel_payment", describe=_describe, on_approved=_payment_approved,
                  on_returned=_payment_returned, on_rejected=_payment_rejected,
                  sample_context={"department_id": 1, "amount": 8450.0})
