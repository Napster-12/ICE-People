"""Requisition approval chain: Department Manager → Line Manager → Finance → Group HR Manager → GCOO / Exco
(31 Oct 2026, at the user's request). The Department Manager step applies when HR raises the requisition; the Line
Manager step goes to the Line Manager above the position's Department Manager.

Revision ID: a6c1e4f87d23
Revises: f3b8d2a5c619
Create Date: 2026-11-01 00:10:00

"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'a6c1e4f87d23'
down_revision = 'f3b8d2a5c619'
branch_labels = None
depends_on = None

NEW_RULES = [
    (1, "Department manager", "@department_manager", 'raised_by == "HR"', 2),
    (2, "Line manager", "@department_line_manager", "", 2),
    (3, "Finance", "Finance", "", 3),
    (4, "Group HR Manager", "Group HR Manager", "", 3),
    (5, "GCOO / Exco", "@gcoo_or_exco", "", 5),
]


def upgrade():
    """The old rules are kept but switched off; requisitions already in approval keep their steps."""
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE routing_rules SET active = 0 WHERE workflow_type = 'requisition'"))
    for level, name, approver, condition, sla in NEW_RULES:
        conn.execute(sa.text("INSERT INTO routing_rules (workflow_type, level, name, approver, condition, sla_days, "
                             "active) VALUES ('requisition', :l, :n, :a, :c, :sla, 1)"),
                     {"l": level, "n": name, "a": approver, "c": condition, "sla": sla})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM routing_rules WHERE workflow_type = 'requisition' AND active = 1"))
    conn.execute(sa.text("UPDATE routing_rules SET active = 1 WHERE workflow_type = 'requisition' "
                         "AND id IN (SELECT MAX(id) FROM routing_rules WHERE workflow_type = 'requisition' "
                         "GROUP BY level, approver)"))
