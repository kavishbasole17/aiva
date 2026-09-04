"""Add AI evaluation column to questionnaire responses (ADR-033).

Revision ID: 0014_questionnaire_ai_evaluation
Revises: 0013_encrypt_sensitive_text

Adds `questionnaire_responses.ai_evaluation` (nullable JSONB) -- the
persisted result of the AI gateway's QuestionnaireEvaluation judgement
(overall score, recommendation, inconsistencies vs. the resume, missing
critical info). This was explicitly scoped out of Milestone 6 pending a
real AI model being deployed; ADR-024 unblocked it, this migration and the
router logic in `routers_questionnaire.py` deliver it.

No RLS/grant changes needed: `questionnaire_responses` already has
FORCE ROW LEVEL SECURITY and the `aiva_app` grant from migration
0004_questionnaires -- a new nullable column on an existing table doesn't
need either repeated (same reasoning as any other additive, non-structural
column migration in this history).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0014_questionnaire_ai_evaluation"
down_revision: str | None = "0013_encrypt_sensitive_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questionnaire_responses",
        sa.Column("ai_evaluation", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questionnaire_responses", "ai_evaluation")
