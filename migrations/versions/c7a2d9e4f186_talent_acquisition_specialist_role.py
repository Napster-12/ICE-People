"""The Recruiter role becomes "Talent Acquisition Specialist", a recruitment-only profile (5 Nov 2026, at the user's
request). Users keep the role; only its name changes.

Revision ID: c7a2d9e4f186
Revises: b4e1f7a93c52
Create Date: 2026-11-05 12:00:00

"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'c7a2d9e4f186'
down_revision = 'b4e1f7a93c52'
branch_labels = None
depends_on = None


def _rename(old, new):
    op.get_bind().execute(sa.text("UPDATE roles SET name = :new WHERE name = :old"), {"new": new, "old": old})


def upgrade():
    _rename("Recruiter", "Talent Acquisition Specialist")


def downgrade():
    _rename("Talent Acquisition Specialist", "Recruiter")
