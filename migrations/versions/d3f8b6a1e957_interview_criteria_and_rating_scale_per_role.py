"""Interview criteria and rating scales are typed per role, not built in (5 Nov 2026, at the user's request): each
JD in the library gets its own interview criteria and rating scale, and each panel its own rating scale. Existing
panels keep their criteria and get the 1-5 scale they were scored on.

Revision ID: d3f8b6a1e957
Revises: c7a2d9e4f186
Create Date: 2026-11-05 15:00:00

"""
import json

from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'd3f8b6a1e957'
down_revision = 'c7a2d9e4f186'
branch_labels = None
depends_on = None

ONE_TO_FIVE = [{"value": n, "label": ""} for n in range(1, 6)]


def upgrade():
    with op.batch_alter_table('jd_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('interview_criteria', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('rating_scale', sa.JSON(), nullable=True))
    with op.batch_alter_table('interview_panels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rating_scale', sa.JSON(), nullable=True))
    op.get_bind().execute(sa.text("UPDATE interview_panels SET rating_scale = :s"), {"s": json.dumps(ONE_TO_FIVE)})


def downgrade():
    with op.batch_alter_table('interview_panels', schema=None) as batch_op:
        batch_op.drop_column('rating_scale')
    with op.batch_alter_table('jd_templates', schema=None) as batch_op:
        batch_op.drop_column('rating_scale')
        batch_op.drop_column('interview_criteria')
