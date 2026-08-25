"""Interview sessions, turns, and consent records with org-scoped RLS.

Revision ID: 0006_interview_sessions
Revises: 0005_interview_slots

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0006_interview_sessions"
down_revision: str | None = "0005_interview_slots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"
ORG_SETTING = "current_setting('aiva.organization_id', true)"
BOOTSTRAP = f"({ORG_SETTING} IS NULL OR {ORG_SETTING} = ''"


def _rls_statements(table: str) -> list[str]:
    # Bootstrap-safe like every other table: unauthenticated token-gated
    # candidate endpoints query with no organization context bound.
    match_clause = f"{BOOTSTRAP} OR {table}.organization_id::text = {ORG_SETTING})"
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
        "interview_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("slot_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resume_id", UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending_consent"),
        sa.Column("plan_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("plan_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "precheck_report", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("precheck_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("asked_turns", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"]),
        sa.ForeignKeyConstraint(["slot_id"], ["interview_slots.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resume_documents.id"]),
    )
    op.create_index(
        "ix_interview_sessions_organization_id", "interview_sessions", ["organization_id"]
    )
    op.create_index(
        "ix_interview_sessions_requisition_id", "interview_sessions", ["requisition_id"]
    )
    op.create_index("ix_interview_sessions_slot_id", "interview_sessions", ["slot_id"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON interview_sessions TO {APP_ROLE}")

    op.create_table(
        "interview_turns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("stt_confidence", sa.Float(), nullable=True),
        sa.Column("stt_model_id", sa.String(length=128), nullable=True),
        sa.Column("tts_model_id", sa.String(length=128), nullable=True),
        sa.Column("answer_audio_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"]),
    )
    op.create_index("ix_interview_turns_organization_id", "interview_turns", ["organization_id"])
    op.create_index("ix_interview_turns_session_id", "interview_turns", ["session_id"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON interview_turns TO {APP_ROLE}")

    op.create_table(
        "interview_consents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("consent_text_version", sa.String(length=32), nullable=False),
        sa.Column("statement_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"]),
    )
    op.create_index(
        "ix_interview_consents_organization_id", "interview_consents", ["organization_id"]
    )
    op.create_index("ix_interview_consents_session_id", "interview_consents", ["session_id"])
    op.execute(f"GRANT SELECT, INSERT ON interview_consents TO {APP_ROLE}")

    for statement in _rls_statements("interview_sessions"):
        op.execute(statement)
    for statement in _rls_statements("interview_turns"):
        op.execute(statement)
    for statement in _rls_statements("interview_consents"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS interview_consents CASCADE")
    op.execute("DROP TABLE IF EXISTS interview_turns CASCADE")
    op.execute("DROP TABLE IF EXISTS interview_sessions CASCADE")
