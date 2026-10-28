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
    "casual_default_hours": ("520", "Casual role estimated hours",
                             "Hours used for casual CTC when a requisition doesn't state them."),
}


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
