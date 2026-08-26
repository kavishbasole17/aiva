"""M9 live-coding workspace: tasks, autosaved code, executions, whiteboard, discussion.

Revision ID: 0009_workspace
Revises: 0008_grants_backfill_0003

All five tables are session-scoped and org-scoped with the same bootstrap-safe
RLS as interview_sessions/turns/consents (public token-gated candidate
endpoints query with no organization context bound). code_snapshots,
code_executions, whiteboard_strokes, and discussion_messages are append-only
event logs — one row per autosave/run/stroke/message, never mutated or
deleted, so they only need SELECT/INSERT grants (same discipline as
interview_consents). coding_tasks is written once at creation time by staff
and otherwise read-only to both sides, so it gets the same SELECT/INSERT-only
grant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0009_workspace"
down_revision: str | None = "0008_grants_backfill_0003"
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
        "coding_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("starter_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"]),
    )
    op.create_index("ix_coding_tasks_organization_id", "coding_tasks", ["organization_id"])
    op.create_index("ix_coding_tasks_session_id", "coding_tasks", ["session_id"])
    op.execute(f"GRANT SELECT, INSERT ON coding_tasks TO {APP_ROLE}")

    op.create_table(
        "code_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["coding_tasks.id"]),
    )
    op.create_index("ix_code_snapshots_organization_id", "code_snapshots", ["organization_id"])
    op.create_index("ix_code_snapshots_task_id", "code_snapshots", ["task_id"])
    op.execute(f"GRANT SELECT, INSERT ON code_snapshots TO {APP_ROLE}")

    op.create_table(
        "code_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("stdin", sa.Text(), nullable=False, server_default=""),
        sa.Column("stdout", sa.Text(), nullable=False, server_default=""),
        sa.Column("stderr", sa.Text(), nullable=False, server_default=""),
        sa.Column("exit_code", sa.BigInteger(), nullable=True),
        sa.Column("timed_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["coding_tasks.id"]),
    )
    op.create_index("ix_code_executions_organization_id", "code_executions", ["organization_id"])
    op.create_index("ix_code_executions_task_id", "code_executions", ["task_id"])
    op.execute(f"GRANT SELECT, INSERT ON code_executions TO {APP_ROLE}")

    op.create_table(
        "whiteboard_strokes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("stroke_payload", JSONB(), nullable=False),
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
        "ix_whiteboard_strokes_organization_id", "whiteboard_strokes", ["organization_id"]
    )
    op.create_index("ix_whiteboard_strokes_session_id", "whiteboard_strokes", ["session_id"])
    op.execute(f"GRANT SELECT, INSERT ON whiteboard_strokes TO {APP_ROLE}")

    op.create_table(
        "discussion_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=True),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("author_label", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["coding_tasks.id"]),
    )
    op.create_index(
        "ix_discussion_messages_organization_id", "discussion_messages", ["organization_id"]
    )
    op.create_index("ix_discussion_messages_session_id", "discussion_messages", ["session_id"])
    op.execute(f"GRANT SELECT, INSERT ON discussion_messages TO {APP_ROLE}")

    for table in (
        "coding_tasks",
        "code_snapshots",
        "code_executions",
        "whiteboard_strokes",
        "discussion_messages",
    ):
        for statement in _rls_statements(table):
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discussion_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS whiteboard_strokes CASCADE")
    op.execute("DROP TABLE IF EXISTS code_executions CASCADE")
    op.execute("DROP TABLE IF EXISTS code_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS coding_tasks CASCADE")
