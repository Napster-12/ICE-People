"""Database-held configuration with typed defaults."""
from decimal import Decimal

from app.extensions import db
from app.models import Setting

DEFAULTS = {
    "fy_start_month": ("3", "Financial year start month", "1–12. Default 3 (March to February)."),
    "overspend_alert_pct": ("90", "Overspend alert threshold (%)",
                            "Finance is alerted when committed + consumed passes this share of a budget line."),
    "sla_reminder_hours": ("24", "Approval reminder after (business hours)",
                           "Inactive approval steps get a reminder after this many business hours."),
    "default_sla_days": ("2", "Default approval SLA (business days)", "Used for new routing rules."),
    "probation_months": ("6", "Probation period (months)", "Default probation length for new starters."),
    "advert_closing_days": ("21", "Advert open for (days)", "Default closing date for a new or re-advertised advert."),
    "advert_ee_statement": ("Icebolethu Group is an equal opportunity employer and embraces the principles of the "
                            "Employment Equity Act. Preference may be given to candidates from designated groups in "
                            "line with our Employment Equity plan.",
                            "Advert EE and equal opportunity statement",
                            "Added to every new advert (JA-004). Recruiters can adjust it per advert."),
    "letter_signatory_name": ("", "Offer letter: who signs",
                              "The name under the signature on offer letters, e.g. Mr. A. Mdala "
                              "(8 Nov 2026). HR Admin sets it under Onboarding → Offer letter and documents."),
    "letter_signatory_title": ("Group Human Resources Manager", "Offer letter: signatory's title",
                               "The job title under the signatory's name."),
    "onboarding_documents": ("ID copy\nHighest qualification\nProof of address\nBank confirmation letter\n"
                             "Tax number (SARS document)\nUpdated CV",
                             "Onboarding documents",
                             "Documents a candidate attaches to accept an offer, one per line (10 Nov 2026). HR Admin "
                             "edits the list under Onboarding → Offer letter and documents."),
    "application_documents": ("ID copy\nHighest qualification certificate\nAcademic transcript",
                              "Documents required when applying",
                              "Every job applicant attaches these, one per line (16 Nov 2026). HR Admin edits the "
                              "list under Onboarding → Offer letter and documents."),
    "application_optional_documents": ("Cover letter", "Optional documents when applying",
                                       "Applicants may attach these, one per line (16 Nov 2026)."),
    "background_checks": ("ID verification\nCriminal record check\nCredit check\nQualification verification\n"
                          "Reference checks",
                          "Background checks",
                          "Checks run on a successful candidate before the offer is sent, one per line (16 Nov 2026). "
                          "HR Admin edits the list under Onboarding → Offer letter and documents."),
    "sage_self_service_url": ("https://online.sage.co.za/U36476/#/signin", "Sage 300 self-service link",
                              "The staff portal's \"Leave and payslips\" tile opens this page (1 Nov 2026)."),
    "itravel_email": ("quotes@i-travel.africa", "i-Travel email address",
                      "Approved travel requests are emailed here as a PDF, with a copy to Finance (14 Nov 2026)."),
    "itravel_email_live": ("0", "Email approved travel requests to i-Travel (1 = on, 0 = off)",
                           "Off (0) until i-Travel goes live (15 Nov 2026, at the user's request): Finance still gets "
                           "the PDF and i-Travel sees the request on the i-Travel dashboard, but nothing is emailed "
                           "to the i-Travel address."),
}
TEXT_KEYS = {"advert_ee_statement", "sage_self_service_url", "letter_signatory_name", "letter_signatory_title",
             "onboarding_documents", "background_checks", "itravel_email",
             "application_documents", "application_optional_documents"}   # every other setting is a number
URL_KEYS = {"sage_self_service_url"}
EMAIL_KEYS = {"itravel_email"}                          # must be an email address
LETTER_KEYS = {"letter_signatory_name", "letter_signatory_title", "onboarding_documents", "background_checks",
               "application_documents", "application_optional_documents"}   # HR Admin's, on the Onboarding templates page                           # must be an https:// address


def get(key, cast=str):
    row = db.session.get(Setting, key)
    value = row.value if row else DEFAULTS.get(key, ("",))[0]
    if cast is Decimal:
        return Decimal(value)
    return cast(value)


def set_value(key, value):
    row = db.session.get(Setting, key)
    if row is None:
        label, help_text = DEFAULTS.get(key, ("", key, ""))[1:]
        row = Setting(key=key, label=label, help=help_text, value=str(value))
        db.session.add(row)
    else:
        row.value = str(value)
    return row


def ensure_defaults():
    for key, (value, label, help_text) in DEFAULTS.items():
        if db.session.get(Setting, key) is None:
            db.session.add(Setting(key=key, value=value, label=label, help=help_text))
