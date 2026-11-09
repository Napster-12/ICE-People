"""Eligibility questions are typed per advert by the Talent Acquisition Specialist (6 Nov 2026, at the user's
request), replacing the questions built from the position and the advert's minimums.

Revision ID: e8c4a2f71b39
Revises: d3f8b6a1e957
Create Date: 2026-11-06 06:00:00

"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'e8c4a2f71b39'
down_revision = 'd3f8b6a1e957'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('eligibility_questions', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('eligibility_questions')
