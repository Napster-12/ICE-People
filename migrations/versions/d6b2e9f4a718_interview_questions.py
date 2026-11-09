"""Interview questions replace criteria and rating scales (8 Nov 2026)

The Department Manager types the questions when returning the shortlist; each is scored 1–5 with a comment. Existing
panels' criteria names become their questions; old scorecards are removed so they can be scored on the questions.
JD criteria and rating scales are dropped.

Revision ID: d6b2e9f4a718
Revises: c4f8a2e6d913
Create Date: 2026-11-08
"""
import json

from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "d6b2e9f4a718"
down_revision = "c4f8a2e6d913"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if "questions" not in {c["name"] for c in sa.inspect(conn).get_columns("interview_panels")}:
        with op.batch_alter_table("interview_panels") as batch:
            batch.add_column(sa.Column("questions", sa.JSON(), nullable=True))
    for panel_id, criteria in conn.execute(sa.text("SELECT id, criteria FROM interview_panels")).fetchall():
        items = json.loads(criteria) if isinstance(criteria, str) else (criteria or [])
        questions = [c["name"] for c in items if isinstance(c, dict) and c.get("name")]
        conn.execute(sa.text("UPDATE interview_panels SET questions = :q WHERE id = :id"),
                     {"q": json.dumps(questions), "id": panel_id})
    with op.batch_alter_table("interview_panels") as batch:
        batch.alter_column("questions", existing_type=sa.JSON(), nullable=False)
        batch.drop_column("criteria")
        batch.drop_column("rating_scale")

    conn.execute(sa.text("DELETE FROM scorecards"))
    with op.batch_alter_table("scorecards") as batch:
        batch.add_column(sa.Column("answers", sa.JSON(), nullable=False, server_default="[]"))
        batch.drop_column("scores")

    with op.batch_alter_table("jd_templates") as batch:
        batch.drop_column("interview_criteria")
        batch.drop_column("rating_scale")


def downgrade():
    with op.batch_alter_table("jd_templates") as batch:
        batch.add_column(sa.Column("interview_criteria", sa.JSON()))
        batch.add_column(sa.Column("rating_scale", sa.JSON()))
    with op.batch_alter_table("scorecards") as batch:
        batch.add_column(sa.Column("scores", sa.JSON(), nullable=False, server_default="{}"))
        batch.drop_column("answers")
    with op.batch_alter_table("interview_panels") as batch:
        batch.add_column(sa.Column("criteria", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("rating_scale", sa.JSON()))
        batch.drop_column("questions")
