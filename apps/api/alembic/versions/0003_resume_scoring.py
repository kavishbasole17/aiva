"""Resume/JD entities with org-scoped RLS.

Revision ID: 0003_resume_scoring
Revises: 0002_core_entities_rls

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0003_resume_scoring"
down_revision: str | None = "0002_core_entities_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"
ORG_SETTING = "current_setting('aiva.organization_id', true)"
BOOTSTRAP = f"({ORG_SETTING} IS NULL OR {ORG_SETTING} = ''"


def _org_match(table: str) -> str:
    return f"{BOOTSTRAP} OR {table}.organization_id::text = {ORG_SETTING})"


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
        "job_descriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "required_skills", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "preferred_skills", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("min_years_experience", sa.BigInteger(), nullable=False, server_default="0"),
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
        "resume_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("candidate_email", sa.String(length=320), nullable=True),
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
        "extracted_fields",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("resume_id", UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("page_number", sa.BigInteger(), nullable=False),
        sa.Column("start_offset", sa.BigInteger(), nullable=False),
        sa.Column("end_offset", sa.BigInteger(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("extractor", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["resume_documents.id"]),
    )
    op.create_table(
        "weight_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("weights", JSONB(), nullable=False),
        sa.Column("auto_reject_below", sa.BigInteger(), nullable=False, server_default="30"),
        sa.Column("hold_below", sa.BigInteger(), nullable=False, server_default="50"),
        sa.Column("highly_recommended_at", sa.BigInteger(), nullable=False, server_default="85"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_table(
        "scoring_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", UUID(as_uuid=True), nullable=False),
        sa.Column("weight_profile_id", UUID(as_uuid=True), nullable=False),
        sa.Column("total_score", sa.BigInteger(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("checks_payload", JSONB(), nullable=False),
        sa.Column("dimensions_payload", JSONB(), nullable=False),
        sa.Column("run_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resume_documents.id"]),
        sa.ForeignKeyConstraint(["weight_profile_id"], ["weight_profiles.id"]),
    )

    for table in ("job_descriptions", "resume_documents", "weight_profiles", "scoring_runs"):
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    op.create_index("ix_job_descriptions_requisition_id", "job_descriptions", ["requisition_id"])
    op.create_index("ix_resume_documents_requisition_id", "resume_documents", ["requisition_id"])
    op.create_index("ix_extracted_fields_resume_id", "extracted_fields", ["resume_id"])
    op.create_index("ix_scoring_runs_run_fingerprint", "scoring_runs", ["run_fingerprint"])

    for statement in _policies("job_descriptions", _org_match("job_descriptions")):
        op.execute(statement)
    for statement in _policies("resume_documents", _org_match("resume_documents")):
        op.execute(statement)
    for statement in _policies(
        "extracted_fields",
        "EXISTS (SELECT 1 FROM resume_documents r WHERE r.id = extracted_fields.resume_id "
        f"AND (r.organization_id::text = {ORG_SETTING}))",
    ):
        op.execute(statement)
    for statement in _policies("weight_profiles", _org_match("weight_profiles")):
        op.execute(statement)
    for statement in _policies("scoring_runs", _org_match("scoring_runs")):
        op.execute(statement)

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON extracted_fields TO {APP_ROLE}")


def downgrade() -> None:
    for table in (
        "scoring_runs",
        "weight_profiles",
        "extracted_fields",
        "resume_documents",
        "job_descriptions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
