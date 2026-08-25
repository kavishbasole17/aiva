"""Backfill missing aiva_app grants on 0004/0005 tables.

Discovered while building M8's integration flow: migrations 0002 granted
table privileges only for tables existing at that time, and 0003 re-granted
for its own tables — but the questionnaire trio (0004) and interview_slots
(0005) were never granted, so every endpoint touching them would fail with
permission denied once the API connected as its runtime role. This migration
closes that gap explicitly rather than editing already-applied history.

Revision ID: 0007_app_role_grants_backfill
Revises: 0006_interview_sessions

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_app_role_grants_backfill"
down_revision: str | None = "0006_interview_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"

TABLES = (
    "questionnaires",
    "questionnaire_invites",
    "questionnaire_responses",
    "interview_slots",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    pass
