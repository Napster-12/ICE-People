"""Applicant profile and documents (16 Nov 2026)

- candidates: title, names, citizenship, ID/passport number (encrypted), date of birth, nationality, work permit,
  alternative phone, address, province, employer, notice period, salaries, driver's licence, own transport,
  languages, voluntary EE details and the documents attached when applying.
- Settings application_documents and application_optional_documents (if not there yet).

Revision ID: d5a1c8e3b947
Revises: c2e7a9d4f615
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "d5a1c8e3b947"
down_revision = "c2e7a9d4f615"
branch_labels = None
depends_on = None

COLUMNS = [
    ("title", sa.String(10)), ("first_names", sa.String(100)), ("surname", sa.String(80)),
    ("sa_citizen", sa.String(3)), ("id_number", app.models.base.EncryptedString()), ("date_of_birth", sa.Date()),
    ("nationality", sa.String(80)), ("work_permit_expiry", sa.Date()), ("alt_phone", sa.String(40)),
    ("street", sa.String(160)), ("suburb", sa.String(120)), ("city", sa.String(120)), ("postal_code", sa.String(10)),
    ("province", sa.String(40)), ("current_employer", sa.String(160)), ("notice_period", sa.String(20)),
    ("current_salary", sa.Numeric(14, 2)), ("expected_salary", sa.Numeric(14, 2)), ("drivers_licence", sa.String(30)),
    ("own_transport", sa.String(3)), ("languages", sa.String(255)), ("gender", sa.String(20)), ("race", sa.String(20)),
    ("disability", sa.String(20)), ("documents", sa.JSON()),
]
SETTINGS = ("application_documents", "application_optional_documents")


def upgrade():
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns("candidates")}
    with op.batch_alter_table("candidates") as batch:
        for name, type_ in COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, type_, nullable=True))
    from app.services.settings import DEFAULTS
    for key in SETTINGS:
        if not conn.execute(sa.text("SELECT 1 FROM settings WHERE key = :k"), {"k": key}).first():
            value, label, help_text = DEFAULTS[key]
            conn.execute(sa.text("INSERT INTO settings (key, value, label, help) VALUES (:k, :v, :l, :h)"),
                         {"k": key, "v": value, "l": label, "h": help_text})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM settings WHERE key IN :keys").bindparams(
        sa.bindparam("keys", expanding=True)), {"keys": list(SETTINGS)})
    with op.batch_alter_table("candidates") as batch:
        for name, _type in reversed(COLUMNS):
            batch.drop_column(name)
