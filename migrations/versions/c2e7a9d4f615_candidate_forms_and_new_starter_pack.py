"""Candidate forms and the new starter pack (16 Nov 2026)

- background_screenings: the POPIA consent's ID number (encrypted) and "signed at".
- offers.code_of_conduct_at: the candidate accepted the Code of Conduct with the offer.
- new_starter_packs: the online New Hire Take-On form (answers encrypted) and the uploaded forms.
- Email templates starter_pack_update and candidate_starter_pack_returned (if not there yet); the welcome email
  (candidate_offer_accepted) links to the pack (only if still the default wording).

Revision ID: c2e7a9d4f615
Revises: b8d4f2a6c193
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "c2e7a9d4f615"
down_revision = "b8d4f2a6c193"
branch_labels = None
depends_on = None

TEMPLATE_KEYS = ("starter_pack_update", "candidate_starter_pack_returned")
OLD_WELCOME = ("Dear {{ name }}\n\nThank you for accepting our offer for the {{ title }} "
               "position. We are excited to welcome you to the team.\n\nPosition: {{ title }}\n"
               "Start date: {{ start_date }}\n\nThank you for sending your onboarding documents. "
               "Our HR team will contact you shortly about your employment contract and your "
               "first day.\n\n"
               "Kind regards\nIcebolethu Group Human Resources")


def upgrade():
    with op.batch_alter_table("background_screenings") as batch:
        batch.add_column(sa.Column("consent_id_number", app.models.base.EncryptedString(), nullable=True))
        batch.add_column(sa.Column("consent_place", sa.String(120), nullable=True))
    with op.batch_alter_table("offers") as batch:
        batch.add_column(sa.Column("code_of_conduct_at", sa.DateTime(), nullable=True))
    op.create_table(
        "new_starter_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("onboarding_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("token", sa.String(64)),
        sa.Column("data", app.models.base.EncryptedString()),
        sa.Column("uploads", sa.JSON()),
        sa.Column("declared_name", sa.String(160)),
        sa.Column("submitted_at", sa.DateTime()),
        sa.Column("submitted_ip", sa.String(64)),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("review_comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_new_starter_packs_case_id", "new_starter_packs", ["case_id"], unique=True)
    op.create_index("ix_new_starter_packs_status", "new_starter_packs", ["status"])
    op.create_index("ix_new_starter_packs_token", "new_starter_packs", ["token"], unique=True)

    conn = op.get_bind()
    from app.services.notifications import DEFAULT_TEMPLATES
    conn.execute(sa.text("UPDATE notification_templates SET body = :new WHERE key = 'candidate_offer_accepted' "
                         "AND body = :old"), {"new": DEFAULT_TEMPLATES["candidate_offer_accepted"][2],
                                              "old": OLD_WELCOME})
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
    conn.execute(sa.text("UPDATE notification_templates SET body = :old WHERE key = 'candidate_offer_accepted' "
                         "AND body = :new"), {"old": OLD_WELCOME,
                                              "new": DEFAULT_TEMPLATES["candidate_offer_accepted"][2]})
    conn.execute(sa.text("DELETE FROM notification_templates WHERE key IN :keys").bindparams(
        sa.bindparam("keys", expanding=True)), {"keys": list(TEMPLATE_KEYS)})
    op.drop_table("new_starter_packs")
    with op.batch_alter_table("offers") as batch:
        batch.drop_column("code_of_conduct_at")
    with op.batch_alter_table("background_screenings") as batch:
        batch.drop_column("consent_place")
        batch.drop_column("consent_id_number")
