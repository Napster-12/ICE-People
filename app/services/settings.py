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
                              "The name under the signature on offer letters and contracts, e.g. Mr. A. Mdala "
                              "(8 Nov 2026). HR Admin sets it under Onboarding → Letter and contract templates."),
    "letter_signatory_title": ("Group Human Resources Manager", "Offer letter: signatory's title",
                               "The job title under the signatory's name."),
    "sage_self_service_url": ("https://online.sage.co.za/U36476/#/signin", "Sage 300 self-service link",
                              "The staff portal's \"Leave and payslips\" tile opens this page (1 Nov 2026)."),
}
TEXT_KEYS = {"advert_ee_statement", "sage_self_service_url", "letter_signatory_name", "letter_signatory_title"}   # every other setting is a number
URL_KEYS = {"sage_self_service_url"}
LETTER_KEYS = {"letter_signatory_name", "letter_signatory_title"}   # HR Admin's, on the Onboarding templates page                           # must be an https:// address


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
