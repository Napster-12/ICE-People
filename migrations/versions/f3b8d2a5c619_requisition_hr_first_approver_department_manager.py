"""A requisition raised by HR goes to the position's Department Manager first; one raised by a manager still goes to
the originator's line manager (31 Oct 2026, at the user's request).

Revision ID: f3b8d2a5c619
Revises: e2a7c9d14b38
Create Date: 2026-10-31 23:59:00

"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'f3b8d2a5c619'
down_revision = 'e2a7c9d14b38'
branch_labels = None
depends_on = None


def upgrade():
    """Requisitions already in approval keep the steps they started with."""
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE routing_rules SET condition = 'raised_by == \"Manager\"' "
                         "WHERE workflow_type = 'requisition' AND active = 1 AND level = 1 "
                         "AND approver = '@line_manager_or_hod' AND (condition = '' OR condition IS NULL)"))
    if not conn.execute(sa.text("SELECT 1 FROM routing_rules WHERE workflow_type = 'requisition' AND active = 1 "
                                "AND approver = '@department_manager'")).first():
        conn.execute(sa.text("INSERT INTO routing_rules (workflow_type, level, name, approver, condition, sla_days, "
                             "active) VALUES ('requisition', 1, 'Department manager', '@department_manager', "
                             "'raised_by == \"HR\"', 2, 1)"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM routing_rules WHERE workflow_type = 'requisition' "
                         "AND approver = '@department_manager'"))
    conn.execute(sa.text("UPDATE routing_rules SET condition = '' WHERE workflow_type = 'requisition' "
                         "AND approver = '@line_manager_or_hod' AND condition = 'raised_by == \"Manager\"'"))
