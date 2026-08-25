"""Interview slots with org-scoped RLS.

Revision ID: 0005_interview_slots
Revises: 0004_questionnaires

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0005_interview_slots"
down_revision: str | None = "0004_questionnaires"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"
ORG_SETTING = "current_setting('aiva.organization_id', true)"


def upgrade() -> None:
    op.create_table(
        "interview_slots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("booked_for_email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"]),
    )
    op.create_index("ix_interview_slots_organization_id", "interview_slots", ["organization_id"])
    op.create_index("ix_interview_slots_requisition_id", "interview_slots", ["requisition_id"])
    op.create_index("ix_interview_slots_start_at", "interview_slots", ["start_at"])

    match = f"({ORG_SETTING} IS NULL OR {ORG_SETTING} = '' OR interview_slots.organization_id::text = {ORG_SETTING})"
    for statement in [
        "ALTER TABLE interview_slots ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE interview_slots FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY interview_slots_select ON interview_slots FOR SELECT USING ({match})",
        f"CREATE POLICY interview_slots_insert ON interview_slots FOR INSERT WITH CHECK ({match})",
        f"CREATE POLICY interview_slots_update ON interview_slots FOR UPDATE USING ({match})",
        f"CREATE POLICY interview_slots_delete ON interview_slots FOR DELETE USING ({match})",
    ]:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS interview_slots CASCADE")
