"""Rename the "Finance / Budget Controller" role to "Finance": the organisation has no budget controller
(31 Oct 2026, at the user's request).

Revision ID: c4e8a2f61b07
Revises: b7c31e0a9d42
Create Date: 2026-10-31 13:00:00

"""
from alembic import op
import sqlalchemy as sa
import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'c4e8a2f61b07'
down_revision = 'b7c31e0a9d42'
branch_labels = None
depends_on = None

OLD, NEW = "Finance / Budget Controller", "Finance"


def _rename(old, new):
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET name = :new WHERE name = :old"), {"old": old, "new": new})
    for table, column in (("routing_rules", "approver"), ("routing_rules", "name"),
                          ("workflow_steps", "approver_rule"), ("workflow_steps", "name")):
        conn.execute(sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"), {"old": old, "new": new})


def upgrade():
    _rename(OLD, NEW)


def downgrade():
    _rename(NEW, OLD)
