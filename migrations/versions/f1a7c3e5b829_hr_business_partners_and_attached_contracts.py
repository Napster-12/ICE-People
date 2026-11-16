"""HR Business Partners per department, Group HR = HR Department Manager, attached contracts (10 Nov 2026)

- departments.hrbp_user_id: each department's HR Business Partner (maintains its positions, attaches contracts).
- Routing rules that named the Group HR Manager role now go to the head of the HR department.
- Contracts aren't generated: the contract templates and onboarding_cases.contract_generated_at are dropped, and
  contract statuses become "Awaiting contract" or "Signed".
- The offer-accepted notifications mention the candidate's documents and the HR BP (only if still the default).

Revision ID: f1a7c3e5b829
Revises: d6b2e9f4a718
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

import app.models.base  # noqa: F401  (EncryptedString)

revision = "f1a7c3e5b829"
down_revision = "d6b2e9f4a718"
branch_labels = None
depends_on = None

CONTRACT_KEYS = ("contract_permanent", "contract_contract", "contract_casual")
OLD_ACCEPTED = ("{{ name }} accepted offer {{ ref }} for {{ title }}.\n\nStart date: {{ start_date }}\n"
                "Employee number: {{ employee_number }}\n\nAn onboarding case has been opened. Please "
                "check the employee number, then prepare the contract. The other applicants for this "
                "advert are marked Not selected; send them the regret letter from the job's messages page.")
OLD_WELCOME = ("Dear {{ name }}\n\nThank you for accepting our offer for the {{ title }} "
               "position. We are excited to welcome you to the team.\n\nPosition: {{ title }}\n"
               "Start date: {{ start_date }}\n\nOur HR team will contact you shortly about your "
               "employment contract and the documents we need before your first day.\n\n"
               "Kind regards\nIcebolethu Group Human Resources")


def upgrade():
    conn = op.get_bind()
    if "hrbp_user_id" not in {c["name"] for c in sa.inspect(conn).get_columns("departments")}:
        with op.batch_alter_table("departments") as batch:
            batch.add_column(sa.Column("hrbp_user_id", sa.Integer(), nullable=True))
            batch.create_index("ix_departments_hrbp_user_id", ["hrbp_user_id"])
            batch.create_foreign_key("fk_departments_hrbp_user_id", "users", ["hrbp_user_id"], ["id"])

    conn.execute(sa.text("UPDATE routing_rules SET approver = '@hr_department_manager' "
                         "WHERE approver = 'Group HR Manager'"))

    conn.execute(sa.text("UPDATE onboarding_cases SET contract_status = 'Awaiting contract' "
                         "WHERE contract_status IN ('Not generated', 'Generated')"))
    if "contract_generated_at" in {c["name"] for c in sa.inspect(conn).get_columns("onboarding_cases")}:
        with op.batch_alter_table("onboarding_cases") as batch:
            batch.drop_column("contract_generated_at")
    conn.execute(sa.text("DELETE FROM document_templates WHERE key IN :keys").bindparams(
        sa.bindparam("keys", expanding=True)), {"keys": list(CONTRACT_KEYS)})

    from app.services.notifications import DEFAULT_TEMPLATES
    for key, old in (("offer_accepted", OLD_ACCEPTED), ("candidate_offer_accepted", OLD_WELCOME)):
        conn.execute(sa.text("UPDATE notification_templates SET body = :new WHERE key = :key AND body = :old"),
                     {"new": DEFAULT_TEMPLATES[key][2], "key": key, "old": old})


def downgrade():
    conn = op.get_bind()
    with op.batch_alter_table("onboarding_cases") as batch:
        batch.add_column(sa.Column("contract_generated_at", sa.DateTime(), nullable=True))
    conn.execute(sa.text("UPDATE onboarding_cases SET contract_status = 'Not generated' "
                         "WHERE contract_status = 'Awaiting contract'"))
    conn.execute(sa.text("UPDATE routing_rules SET approver = 'Group HR Manager' "
                         "WHERE approver = '@hr_department_manager'"))
    with op.batch_alter_table("departments") as batch:
        batch.drop_constraint("fk_departments_hrbp_user_id", type_="foreignkey")
        batch.drop_index("ix_departments_hrbp_user_id")
        batch.drop_column("hrbp_user_id")
    # The contract templates come back from documents.ensure_documents() only if restored in code.
