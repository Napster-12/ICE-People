"""Job grades become the occupational levels, rank for rank (5 Nov 2026, at the user's request): Intern → Support /
Unskilled Staff, Junior → Skilled Staff / Technical / Junior Management / Supervisor, Senior → Professional /
Experienced / Specialists / Mid-Management, Manager → Senior Management, Exco → Top Management. Only the names
change, so every record keeps its grade and rank conditions still hold.

Revision ID: b4e1f7a93c52
Revises: 6b9d54c1ba5b
Create Date: 2026-11-05 10:00:00

"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'b4e1f7a93c52'
down_revision = '6b9d54c1ba5b'
branch_labels = None
depends_on = None

LEVELS = [
    (1, "Support / Unskilled Staff"),
    (2, "Skilled Staff / Technical / Junior Management / Supervisor"),
    (3, "Professional / Experienced / Specialists / Mid-Management"),
    (4, "Senior Management (HODs, Regional Managers)"),
    (5, "Top Management (CEOs, EXCO, Directors, Founders)"),
]
OLD = [(1, "Intern"), (2, "Junior"), (3, "Senior"), (4, "Manager"), (5, "Exco")]


def _rename(names):
    conn = op.get_bind()
    for rank, name in names:
        conn.execute(sa.text("UPDATE job_grades SET name = :n WHERE grade = :g"), {"n": name, "g": rank})


def upgrade():
    _rename(LEVELS)


def downgrade():
    _rename(OLD)
