"""Add reminder-sent tracking columns to interview slots (ADR-034).

Revision ID: 0015_interview_reminders
Revises: 0014_questionnaire_ai_evaluation

Adds `interview_slots.reminder_24h_sent_at` and `reminder_1h_sent_at`
(nullable timestamps) so a reminder-run endpoint can find booked slots whose
reminder window has opened and hasn't been sent yet, and mark them sent
idempotently -- the same "overwrite in place, never re-derive from nothing"
discipline the rest of this schema uses for anything that must not fire
twice.

No RLS/grant changes needed: `interview_slots` already has FORCE ROW LEVEL
SECURITY and the `aiva_app` grant from migration 0005_interview_slots -- a
new nullable column on an existing table doesn't need either repeated.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_interview_reminders"
down_revision: str | None = "0014_questionnaire_ai_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_slots",
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interview_slots",
        sa.Column("reminder_1h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_slots", "reminder_1h_sent_at")
    op.drop_column("interview_slots", "reminder_24h_sent_at")
