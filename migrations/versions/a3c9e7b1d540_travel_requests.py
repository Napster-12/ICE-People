"""Travel requests and the i-Travel role (14 Nov 2026)

- travel_requests: the i-Travel travel request form, digitised (TRF-…).
- The "i-Travel" role, which books approved requests and sends them to Finance for payment.
- Routing rules: "travel" (the requester's manager) and "travel_payment" (Finance), if none yet.
- The itravel_email setting and the travel_status / travel_booking email templates.

Revision ID: a3c9e7b1d540
Revises: f1a7c3e5b829
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "a3c9e7b1d540"
down_revision = "f1a7c3e5b829"
branch_labels = None
depends_on = None

RULES = [("travel", 1, "Manager", "@originator_manager"), ("travel_payment", 1, "Finance", "Finance")]
TEMPLATE_KEYS = ("travel_status", "travel_booking")


def upgrade():
    op.create_table(
        "travel_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id")),
        sa.Column("client_name", sa.String(160), nullable=False),
        sa.Column("client_address", sa.String(255)),
        sa.Column("client_city", sa.String(120)),
        sa.Column("client_zip", sa.String(20)),
        sa.Column("client_phone", sa.String(40)),
        sa.Column("client_email", sa.String(255)),
        sa.Column("client_code", sa.String(60)),
        sa.Column("booker_name", sa.String(160)),
        sa.Column("booker_phone", sa.String(40)),
        sa.Column("booker_email", sa.String(255)),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approver_name", sa.String(160)),
        sa.Column("approver_phone", sa.String(40)),
        sa.Column("approver_email", sa.String(255)),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("travellers_json", app.models.base.EncryptedString()),
        sa.Column("flights_json", sa.Text()),
        sa.Column("car_hire_json", sa.Text()),
        sa.Column("driver_details", sa.String(255)),
        sa.Column("accommodation_json", sa.Text()),
        sa.Column("auxiliary_json", sa.Text()),
        sa.Column("form_file_id", sa.Integer(), sa.ForeignKey("stored_files.id")),
        sa.Column("sent_to_itravel_at", sa.DateTime()),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("supplier_reference", sa.String(80)),
        sa.Column("payment_note", sa.Text()),
        sa.Column("sent_to_finance_at", sa.DateTime()),
        sa.Column("sent_to_finance_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("paid_on", sa.Date()),
        sa.Column("payment_reference", sa.String(80)),
        sa.Column("paid_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_travel_requests_reference", "travel_requests", ["reference"], unique=True)
    op.create_index("ix_travel_requests_status", "travel_requests", ["status"])
    op.create_index("ix_travel_requests_requester_id", "travel_requests", ["requester_id"])
    op.create_index("ix_travel_requests_department_id", "travel_requests", ["department_id"])
    op.create_index("ix_travel_requests_created_at", "travel_requests", ["created_at"])

    conn = op.get_bind()
    if not conn.execute(sa.text("SELECT 1 FROM roles WHERE name = 'i-Travel'")).first():
        conn.execute(sa.text("INSERT INTO roles (name) VALUES ('i-Travel')"))
    for workflow_type, level, name, approver in RULES:
        if not conn.execute(sa.text("SELECT 1 FROM routing_rules WHERE workflow_type = :t AND active = TRUE"),
                            {"t": workflow_type}).first():
            conn.execute(sa.text("INSERT INTO routing_rules (workflow_type, level, name, approver, condition, sla_days, "
                                 "active) VALUES (:t, :l, :n, :a, '', 2, TRUE)"),
                         {"t": workflow_type, "l": level, "n": name, "a": approver})
    if not conn.execute(sa.text("SELECT 1 FROM settings WHERE key = 'itravel_email'")).first():
        from app.services.settings import DEFAULTS
        value, label, help_text = DEFAULTS["itravel_email"]
        conn.execute(sa.text("INSERT INTO settings (key, value, label, help) VALUES ('itravel_email', :v, :l, :h)"),
                     {"v": value, "l": label, "h": help_text})
    from app.services.notifications import DEFAULT_TEMPLATES
    columns = {c["name"] for c in sa.inspect(conn).get_columns("notification_templates")}
    for key in TEMPLATE_KEYS:
        if conn.execute(sa.text("SELECT 1 FROM notification_templates WHERE key = :k"), {"k": key}).first():
            continue
        name, subject, body = DEFAULT_TEMPLATES[key]
        if "updated_at" in columns:
            conn.execute(sa.text("INSERT INTO notification_templates (key, name, subject, body, updated_at) "
                                 "VALUES (:k, :n, :s, :b, CURRENT_TIMESTAMP)"),
                         {"k": key, "n": name, "s": subject, "b": body})
        else:
            conn.execute(sa.text("INSERT INTO notification_templates (key, name, subject, body) VALUES (:k, :n, :s, :b)"),
                         {"k": key, "n": name, "s": subject, "b": body})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM notification_templates WHERE key IN ('travel_status', 'travel_booking')"))
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'itravel_email'"))
    conn.execute(sa.text("DELETE FROM routing_rules WHERE workflow_type IN ('travel', 'travel_payment')"))
    conn.execute(sa.text("DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles WHERE name = 'i-Travel')"))
    conn.execute(sa.text("DELETE FROM roles WHERE name = 'i-Travel'"))
    op.drop_table("travel_requests")
