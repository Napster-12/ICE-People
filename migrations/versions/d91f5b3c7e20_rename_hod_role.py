"""Rename the "HOD" role to "Department Manager": the organisation has line managers and department managers, not
HODs (31 Oct 2026, at the user's request).

Revision ID: d91f5b3c7e20
Revises: c4e8a2f61b07
Create Date: 2026-10-31 14:00:00

"""
from alembic import op
import sqlalchemy as sa
import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'd91f5b3c7e20'
down_revision = 'c4e8a2f61b07'
branch_labels = None
depends_on = None

OLD, NEW = "HOD", "Department Manager"


def _rename(old, new):
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET name = :new WHERE name = :old"), {"old": old, "new": new})
    for table, column in (("routing_rules", "approver"), ("workflow_steps", "approver_rule")):
        conn.execute(sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"), {"old": old, "new": new})


def upgrade():
    _rename(OLD, NEW)


def downgrade():
    _rename(NEW, OLD)
