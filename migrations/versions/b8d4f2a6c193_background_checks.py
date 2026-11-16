"""Background checks before the offer (16 Nov 2026)

- background_screenings: one per application, with the candidate's online consent (POPIA).
- background_checks: each check's result (Clear / Adverse), recorded by HR Admin or the department's HR BP.
- The background_checks setting and the three screening email templates (if not there yet); the interview_passed
  notification mentions the checks (only if still the default wording).

Revision ID: b8d4f2a6c193
Revises: a3c9e7b1d540
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "b8d4f2a6c193"
down_revision = "a3c9e7b1d540"
branch_labels = None
depends_on = None

TEMPLATE_KEYS = ("screening_needed", "screening_update", "candidate_screening_consent")
OLD_PASSED = ("{{ decided_by }} marked {{ name }} successful after the interview for {{ title }}.\n\n"
              "Candidate: {{ name }}\nApplication: {{ ref }}\nPanel score: {{ average }}%"
              "{% if comment %}\nComment: {{ comment }}{% endif %}\n\n"
              "Please prepare and send the offer letter.")


def upgrade():
    op.create_table(
        "background_screenings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("token", sa.String(64)),
        sa.Column("consent_requested_at", sa.DateTime()),
        sa.Column("consent_at", sa.DateTime()),
        sa.Column("consent_name", sa.String(160)),
        sa.Column("consent_ip", sa.String(64)),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("started_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_background_screenings_application_id", "background_screenings", ["application_id"],
                    unique=True)
    op.create_index("ix_background_screenings_status", "background_screenings", ["status"])
    op.create_index("ix_background_screenings_token", "background_screenings", ["token"], unique=True)
    op.create_table(
        "background_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("screening_id", sa.Integer(), sa.ForeignKey("background_screenings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_reference", sa.String(80)),
        sa.Column("completed_on", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("recorded_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_background_checks_screening_id", "background_checks", ["screening_id"])

    conn = op.get_bind()
    from app.services.notifications import DEFAULT_TEMPLATES
    conn.execute(sa.text("UPDATE notification_templates SET body = :new WHERE key = 'interview_passed' AND body = :old"),
                 {"new": DEFAULT_TEMPLATES["interview_passed"][2], "old": OLD_PASSED})
    if not conn.execute(sa.text("SELECT 1 FROM settings WHERE key = 'background_checks'")).first():
        from app.services.settings import DEFAULTS
        value, label, help_text = DEFAULTS["background_checks"]
        conn.execute(sa.text("INSERT INTO settings (key, value, label, help) VALUES ('background_checks', :v, :l, :h)"),
                     {"v": value, "l": label, "h": help_text})
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
    from app.services.notifications import DEFAULT_TEMPLATES
    conn.execute(sa.text("UPDATE notification_templates SET body = :old WHERE key = 'interview_passed' AND body = :new"),
                 {"old": OLD_PASSED, "new": DEFAULT_TEMPLATES["interview_passed"][2]})
    conn.execute(sa.text("DELETE FROM notification_templates WHERE key IN :keys").bindparams(
        sa.bindparam("keys", expanding=True)), {"keys": list(TEMPLATE_KEYS)})
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'background_checks'"))
    op.drop_table("background_checks")
    op.drop_table("background_screenings")
