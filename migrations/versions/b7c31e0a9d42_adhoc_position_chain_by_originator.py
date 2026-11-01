"""Ad-hoc position approval chain by originator: a manager's request goes to Finance then Exco; HR's request
goes to the Department Manager, Finance, then Exco (decided 31 Oct 2026). Group HR Manager leaves the chain.

Revision ID: b7c31e0a9d42
Revises: 98550cdaa9d9
Create Date: 2026-10-31 12:00:00

"""
from alembic import op
import sqlalchemy as sa
import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'b7c31e0a9d42'
down_revision = '98550cdaa9d9'
branch_labels = None
depends_on = None

NEW_RULES = [
    (1, "Department manager", "@department_manager", 'raised_by == "HR"', 2),
    (2, "Finance (unbudgeted)", "Finance / Budget Controller", "", 3),
    (3, "GCOO / Exco", "@gcoo_or_exco", "", 5),
]


def upgrade():
    """The old rules are kept but switched off, so HR Admin can see what changed; requests already in approval
    keep the steps they started with."""
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE routing_rules SET active = 0 WHERE workflow_type = 'adhoc_position'"))
    for level, name, approver, condition, sla in NEW_RULES:
        conn.execute(sa.text("INSERT INTO routing_rules (workflow_type, level, name, approver, condition, sla_days, "
                             "active) VALUES ('adhoc_position', :l, :n, :a, :c, :sla, 1)"),
                     {"l": level, "n": name, "a": approver, "c": condition, "sla": sla})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM routing_rules WHERE workflow_type = 'adhoc_position' AND active = 1"))
    previous = conn.execute(sa.text("SELECT MAX(id) FROM routing_rules WHERE workflow_type = 'adhoc_position' "
                                    "GROUP BY level")).scalars().all()
    for rule_id in previous:
        conn.execute(sa.text("UPDATE routing_rules SET active = 1 WHERE id = :i"), {"i": rule_id})
