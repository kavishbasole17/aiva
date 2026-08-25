"""Backfill missing aiva_app grants on 0003 (resume/scoring) tables.

Discovered while restoring a local dev stack from scratch and running the
full integration suite: migration 0003 created five tables (job_descriptions,
resume_documents, extracted_fields, weight_profiles, scoring_runs) but only
granted aiva_app privileges on extracted_fields, leaving the other four
completely inaccessible to the runtime role. This is the same class of gap
0007 closed for the questionnaire/interview_slots tables — 0007 just didn't
happen to cover 0003's tables since it was scoped to the M8 flow that found
it. Verified directly against pg_tables/has_table_privilege that this list is
now the complete remaining gap: interview_turns/interview_consents
intentionally omit UPDATE/DELETE (immutable evidence records, never mutated
or deleted by application code) and are left as-is.

Revision ID: 0008_grants_backfill_0003
Revises: 0007_app_role_grants_backfill

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_grants_backfill_0003"
down_revision: str | None = "0007_app_role_grants_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"

TABLES = (
    "job_descriptions",
    "resume_documents",
    "weight_profiles",
    "scoring_runs",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    pass
