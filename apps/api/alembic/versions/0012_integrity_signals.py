"""M11 integrity signals: browser-reported focus/visibility events.

Revision ID: 0012_integrity_signals
Revises: 0011_dsar_update_grants

Scoped deliberately: face/gaze-based proctoring (InsightFace/MediaPipe) is
GPU-model-dependent and was already flagged deferred to deployment across
M8/M9's docs — this migration does not attempt it. What ships here is a
real, zero-ML-dependency signal that's useful today: the browser reporting
when the candidate's tab loses focus, exits fullscreen, or becomes hidden
during an active interview. Bootstrap-safe RLS, same as interview_sessions
— the public token-gated candidate endpoint posts with no organization
context bound. Append-only (SELECT/INSERT only), same discipline as every
other event-log table in this schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0012_integrity_signals"
down_revision: str | None = "0011_dsar_update_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"
ORG_SETTING = "current_setting('aiva.organization_id', true)"
BOOTSTRAP = f"({ORG_SETTING} IS NULL OR {ORG_SETTING} = ''"


def _rls_statements(table: str) -> list[str]:
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
        "integrity_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"]),
    )
    op.create_index(
        "ix_integrity_signals_organization_id", "integrity_signals", ["organization_id"]
    )
    op.create_index("ix_integrity_signals_session_id", "integrity_signals", ["session_id"])
    op.execute(f"GRANT SELECT, INSERT ON integrity_signals TO {APP_ROLE}")

    for statement in _rls_statements("integrity_signals"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS integrity_signals CASCADE")
