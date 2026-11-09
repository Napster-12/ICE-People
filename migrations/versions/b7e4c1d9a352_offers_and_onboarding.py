"""Interview decision, offers, onboarding cases and document templates (8 Nov 2026)

Revision ID: b7e4c1d9a352
Revises: a9d3e6f2c871
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "b7e4c1d9a352"
down_revision = "a9d3e6f2c871"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("applications") as batch:
        batch.add_column(sa.Column("successful_at", sa.DateTime()))
        batch.add_column(sa.Column("successful_by_id", sa.Integer()))
        batch.add_column(sa.Column("decision_comment", sa.Text()))
        batch.create_foreign_key("fk_applications_successful_by", "users", ["successful_by_id"], ["id"])

    op.create_table(
        "offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("ctc", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("employment_type", sa.String(20), nullable=False),
        sa.Column("contract_end_date", sa.Date()),
        sa.Column("conditions", sa.Text()),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("needs_approval", sa.Boolean(), nullable=False),
        sa.Column("token", sa.String(64)),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("responded_at", sa.DateTime()),
        sa.Column("response_ip", sa.String(64)),
        sa.Column("decline_reason", sa.Text()),
        sa.Column("letter_file_id", sa.Integer(), sa.ForeignKey("stored_files.id")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_offers_reference", "offers", ["reference"], unique=True)
    op.create_index("ix_offers_application_id", "offers", ["application_id"])
    op.create_index("ix_offers_status", "offers", ["status"])
    op.create_index("ix_offers_token", "offers", ["token"], unique=True)
    op.create_index("ix_offers_created_at", "offers", ["created_at"])

    op.create_table(
        "onboarding_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id")),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("offers.id")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("contract_status", sa.String(20), nullable=False),
        sa.Column("contract_generated_at", sa.DateTime()),
        sa.Column("contract_signed_on", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_onboarding_cases_reference", "onboarding_cases", ["reference"], unique=True)
    for col in ("employee_id", "application_id", "offer_id", "start_date", "status", "created_at"):
        op.create_index(f"ix_onboarding_cases_{col}", "onboarding_cases", [col])

    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_document_templates_created_at", "document_templates", ["created_at"])


def downgrade():
    op.drop_table("document_templates")
    op.drop_table("onboarding_cases")
    op.drop_table("offers")
    with op.batch_alter_table("applications") as batch:
        batch.drop_constraint("fk_applications_successful_by", type_="foreignkey")
        batch.drop_column("decision_comment")
        batch.drop_column("successful_by_id")
        batch.drop_column("successful_at")
