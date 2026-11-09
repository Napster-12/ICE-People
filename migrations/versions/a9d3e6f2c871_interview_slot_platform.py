"""Interview slot platform and meeting details (8 Nov 2026)

Revision ID: a9d3e6f2c871
Revises: e8c4a2f71b39
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "a9d3e6f2c871"
down_revision = "e8c4a2f71b39"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("interview_slots") as batch:
        batch.add_column(sa.Column("platform", sa.String(30), nullable=False, server_default="In person"))
        batch.add_column(sa.Column("meeting_id", sa.String(64)))
        batch.add_column(sa.Column("passcode", sa.String(64)))


def downgrade():
    with op.batch_alter_table("interview_slots") as batch:
        batch.drop_column("passcode")
        batch.drop_column("meeting_id")
        batch.drop_column("platform")
