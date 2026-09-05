"""Encrypt sensitive text columns at rest (ADR-025).

Revision ID: 0013_encrypt_sensitive_text
Revises: 0012_integrity_signals

Converts the highest-sensitivity text columns from plain `TEXT` to `BYTEA`:
`resume_documents.full_text`, `extracted_fields.value`,
`extracted_fields.source_quote`, `interview_turns.answer_text`. The
application layer (`app/crypto.py`'s `EncryptedText` SQLAlchemy
TypeDecorator) transparently encrypts on write and decrypts on read with
AES-256-GCM, so every other module keeps reading these as plain Python
strings — only the physical bytes on disk change.

This repo has no production data yet (dev/demo only per docs/PLAN.md), so
existing rows are converted via `convert_to(col, 'UTF8')` — a raw byte
reinterpretation, NOT encryption. Any row written before this migration
will fail to decrypt (`DecryptionError`) until it is rewritten. For a fresh
`docker compose up` + migrate + seed flow (the documented quickstart) this
is a non-issue; a real deployment with existing rows would need a one-time
re-encryption backfill script, intentionally not built here since there is
no real data to backfill yet.

Column/table privileges granted to `aiva_app` by earlier migrations are
unaffected by a column type change — no new GRANT statements needed here.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_encrypt_sensitive_text"
down_revision: str | None = "0012_integrity_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("resume_documents", "full_text"),
    ("extracted_fields", "value"),
    ("extracted_fields", "source_quote"),
    ("interview_turns", "answer_text"),
]


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.LargeBinary(),
            postgresql_using=f"convert_to({column}, 'UTF8')",
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Text(),
            postgresql_using=f"convert_from({column}, 'UTF8')",
        )
