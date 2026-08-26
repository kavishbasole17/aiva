"""M11 DSAR: grant UPDATE on the tables holding candidate-authored PII that
weren't previously mutable.

Revision ID: 0011_dsar_update_grants
Revises: 0010_faq_and_evaluation

`code_snapshots`, `code_executions`, `discussion_messages`, and
`evaluation_reports` were deliberately append-only (SELECT/INSERT-only,
ADR-019/020/021 precedent — evidence/log rows are never mutated by routine
application code). A GDPR/CCPA erasure request is the one legitimate,
rare, staff/admin-gated exception: DSAR erasure overwrites (never deletes)
the specific PII-bearing columns in place, preserving row counts and
non-PII content for audit/statistical integrity. This grants UPDATE only —
not DELETE — keeping "evidence rows are never removed" intact while making
erasure possible. See ADR-022.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_dsar_update_grants"
down_revision: str | None = "0010_faq_and_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"

TABLES = (
    "code_snapshots",
    "code_executions",
    "discussion_messages",
    "evaluation_reports",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT UPDATE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"REVOKE UPDATE ON {table} FROM {APP_ROLE}")
