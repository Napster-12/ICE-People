"""Light / dark theme per account (16 Nov 2026, from IGSP)

Revision ID: e7b3d9f1a264
Revises: d5a1c8e3b947
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "e7b3d9f1a264"
down_revision = "d5a1c8e3b947"
branch_labels = None
depends_on = None


def upgrade():
    if "theme" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("theme", sa.String(10), nullable=False, server_default="light"))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("theme")
