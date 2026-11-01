"""Job grades become Intern, Junior, Senior, Manager and Exco (ranks 1-5) and carry no salary: the salary band
columns and the casual-hours setting go, and requisitions are costed from the position's budgeted CTC
(31 Oct 2026, at the user's request).

Records on the old grades 1-12 move to the new grade by rank: 1-3 Junior, 4-7 Senior, 8-11 Manager, 12 Exco.

Revision ID: e2a7c9d14b38
Revises: d5f3d0674ff9
Create Date: 2026-10-31 23:30:00

"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  custom column types (EncryptedString)

# revision identifiers, used by Alembic.
revision = 'e2a7c9d14b38'
down_revision = 'd5f3d0674ff9'
branch_labels = None
depends_on = None

GRADES = [(1, "Intern"), (2, "Junior"), (3, "Senior"), (4, "Manager"), (5, "Exco")]
REFERENCES = [("employees", "job_grade_id"), ("approved_positions", "job_grade_id"),
              ("position_changes", "new_job_grade_id"), ("requisitions", "job_grade_id")]


def _new_rank(old_rank):
    if old_rank <= 3:
        return 2
    if old_rank <= 7:
        return 3
    if old_rank <= 11:
        return 4
    return 5


def upgrade():
    conn = op.get_bind()
    old = conn.execute(sa.text("SELECT id, grade FROM job_grades")).all()
    if {name for (name,) in conn.execute(sa.text("SELECT name FROM job_grades"))} != {n for _, n in GRADES}:
        # Move the old grades out of the way of ranks 1-5, add the new grades, re-point every record, then drop
        # the old grades.
        conn.execute(sa.text("UPDATE job_grades SET grade = grade + 1000"))
        new_ids = {}
        for rank, name in GRADES:
            conn.execute(sa.text("INSERT INTO job_grades (grade, name, band_min, band_max, hourly_rate) "
                                 "VALUES (:g, :n, 0, 0, 0)"), {"g": rank, "n": name})
            new_ids[rank] = conn.execute(sa.text("SELECT id FROM job_grades WHERE grade = :g"), {"g": rank}).scalar()
        for old_id, old_rank in old:
            for table, column in REFERENCES:
                conn.execute(sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
                             {"new": new_ids[_new_rank(old_rank)], "old": old_id})
        conn.execute(sa.text("DELETE FROM job_grades WHERE grade > 1000"))
    with op.batch_alter_table('job_grades', schema=None) as batch_op:
        batch_op.drop_column('band_min')
        batch_op.drop_column('band_max')
        batch_op.drop_column('hourly_rate')
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'casual_default_hours'"))


def downgrade():
    # The salary columns come back empty (0); the old grades 1-12 are not restored.
    with op.batch_alter_table('job_grades', schema=None) as batch_op:
        batch_op.add_column(sa.Column('band_min', sa.Numeric(14, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('band_max', sa.Numeric(14, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('hourly_rate', sa.Numeric(10, 2), nullable=False, server_default='0'))
