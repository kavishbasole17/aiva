"""Questionnaire entities with org-scoped RLS.

Revision ID: 0004_questionnaires
Revises: 0003_resume_scoring

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0004_questionnaires"
down_revision: str | None = "0003_resume_scoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"
ORG_SETTING = "current_setting('aiva.organization_id', true)"
BOOTSTRAP = f"({ORG_SETTING} IS NULL OR {ORG_SETTING} = ''"


def _policies(table: str, match_clause: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({match_clause})",
        f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({match_clause})",
        f"CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({match_clause})",
        f"CREATE POLICY {table}_delete ON {table} FOR DELETE USING ({match_clause})",
    ]


def upgrade() -> None:
    op.create_table(
        "questionnaires",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("questions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"]),
    )
    op.create_table(
        "questionnaire_invites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("questionnaire_id", UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["questionnaire_id"], ["questionnaires.id"]),
    )
    op.create_table(
        "questionnaire_responses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("invite_id", UUID(as_uuid=True), nullable=False),
        sa.Column("answers", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("history", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "missing_required", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["invite_id"], ["questionnaire_invites.id"]),
    )

    for table in ("questionnaires", "questionnaire_invites", "questionnaire_responses"):
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    op.create_index("ix_questionnaires_requisition_id", "questionnaires", ["requisition_id"])
    op.create_index(
        "ix_questionnaire_invites_questionnaire_id", "questionnaire_invites", ["questionnaire_id"]
    )
    op.create_index(
        "ix_questionnaire_responses_invite_id", "questionnaire_responses", ["invite_id"]
    )

    for statement in _policies(
        "questionnaires", f"{BOOTSTRAP} OR questionnaires.organization_id::text = {ORG_SETTING})"
    ):
        op.execute(statement)
    for statement in _policies(
        "questionnaire_invites",
        f"{BOOTSTRAP} OR questionnaire_invites.organization_id::text = {ORG_SETTING})",
    ):
        op.execute(statement)
    for statement in _policies(
        "questionnaire_responses",
        f"{BOOTSTRAP} OR questionnaire_responses.organization_id::text = {ORG_SETTING})",
    ):
        op.execute(statement)


def downgrade() -> None:
    for table in ("questionnaire_responses", "questionnaire_invites", "questionnaires"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
