from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, IntegerField, MultipleFileField, SelectField, TextAreaField
from wtforms.validators import NumberRange, Optional

from app.models.org import EMPLOYMENT_TYPES


def _int_or_none(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value or None


class RequisitionForm(FlaskForm):
    """Title, department, cost centre, grade and headcount type come from the chosen approved position."""
    approved_position_id = SelectField("Approved position", coerce=_int_or_none, validate_choice=False)
    employment_type = SelectField("Employment type", choices=[("", "Choose…")] + [(t, t) for t in EMPLOYMENT_TYPES])
    contract_end_date = DateField("Contract end date", validators=[Optional()])
    required_start_date = DateField("Required start date", validators=[Optional()])
    estimated_hours = IntegerField("Estimated hours (casual)", validators=[Optional(), NumberRange(min=1, max=5000)])
    is_executive = BooleanField("Executive / strategic role")
    justification = TextAreaField("Justification")
    attachments = MultipleFileField("Attachments")

    def set_choices(self, ref):
        self.approved_position_id.choices = [(0, "Choose…")] + [(p.id, str(p)) for p in ref["positions"]]

    def cleaned(self):
        fields = ["approved_position_id", "employment_type", "contract_end_date", "required_start_date",
                  "estimated_hours", "is_executive", "justification"]
        data = {f: getattr(self, f).data for f in fields}
        data["justification"] = (data["justification"] or "").strip()
        data["employment_type"] = data["employment_type"] or None
        data["is_executive"] = bool(data["is_executive"])
        return data
