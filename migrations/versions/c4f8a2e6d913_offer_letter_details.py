"""Offer letter details: salutation, address, work location, probation, accepted copy (8 Nov 2026)

Revision ID: c4f8a2e6d913
Revises: b7e4c1d9a352
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "c4f8a2e6d913"
down_revision = "b7e4c1d9a352"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("offers") as batch:
        batch.add_column(sa.Column("salutation", sa.String(10)))
        batch.add_column(sa.Column("candidate_address", sa.Text()))
        batch.add_column(sa.Column("work_location", sa.String(255)))
        batch.add_column(sa.Column("probation_months", sa.Integer()))
        batch.add_column(sa.Column("accepted_file_id", sa.Integer()))
        batch.create_foreign_key("fk_offers_accepted_file", "stored_files", ["accepted_file_id"], ["id"])


def downgrade():
    with op.batch_alter_table("offers") as batch:
        batch.drop_constraint("fk_offers_accepted_file", type_="foreignkey")
        for col in ("accepted_file_id", "probation_months", "work_location", "candidate_address", "salutation"):
            batch.drop_column(col)
