"""M10: RAG FAQ documents (pgvector) and evaluation reports.

Revision ID: 0010_faq_and_evaluation
Revises: 0009_workspace

`faq_documents` is bootstrap-safe RLS like interview_sessions — the public,
token-gated candidate FAQ endpoint queries with no organization context
bound. `evaluation_reports` is staff-only (no public endpoint ever reads or
writes it), so it uses the same non-bootstrap-relevant policy shape as the
other org-scoped staff tables (the bootstrap clause is harmless there too:
it only ever matches when no org context is bound at all, which never
happens on an authenticated staff request). Both are append-only from the
application's perspective (SELECT/INSERT grants only), matching
coding_tasks/scoring_runs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0010_faq_and_evaluation"
down_revision: str | None = "0009_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "aiva_app"
ORG_SETTING = "current_setting('aiva.organization_id', true)"
BOOTSTRAP = f"({ORG_SETTING} IS NULL OR {ORG_SETTING} = ''"
FAQ_EMBEDDING_DIM = 384


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
        "faq_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(FAQ_EMBEDDING_DIM), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=128), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_faq_documents_organization_id", "faq_documents", ["organization_id"])
    op.create_index("ix_faq_documents_requisition_id", "faq_documents", ["requisition_id"])
    # ivfflat needs at least one row per list at ANALYZE time to be useful,
    # but is safe to create against an empty table — it just starts as a
    # sequential-scan-equivalent until enough rows exist.
    op.execute(
        "CREATE INDEX ix_faq_documents_embedding ON faq_documents "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(f"GRANT SELECT, INSERT ON faq_documents TO {APP_ROLE}")

    op.create_table(
        "evaluation_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", UUID(as_uuid=True), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("overall_score", sa.BigInteger(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("generated_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resume_documents.id"]),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"]),
    )
    op.create_index(
        "ix_evaluation_reports_organization_id", "evaluation_reports", ["organization_id"]
    )
    op.create_index(
        "ix_evaluation_reports_requisition_id", "evaluation_reports", ["requisition_id"]
    )
    op.create_index("ix_evaluation_reports_resume_id", "evaluation_reports", ["resume_id"])
    op.execute(f"GRANT SELECT, INSERT ON evaluation_reports TO {APP_ROLE}")

    for table in ("faq_documents", "evaluation_reports"):
        for statement in _rls_statements(table):
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evaluation_reports CASCADE")
    op.execute("DROP TABLE IF EXISTS faq_documents CASCADE")
