"""M11 DSAR (Data Subject Access Request): export or erase every record tied
to a candidate's email, in one place.

Admin-only — deliberately narrower than the STAFF_ROLES every other router
in this file uses, because erasure is destructive and rare, not routine
recruiter workflow. Export is read-only and uses the same SELECT grants
every other router already has. Erasure never deletes rows (preserving the
"evidence is never removed" discipline interview_turns/consents and the
M9/M10 append-only tables already established) — it overwrites the
specific PII-bearing columns in place via a new, narrowly-scoped UPDATE
grant (migration 0011, ADR-022), keeping row counts and non-PII content
(scores, verdicts, staff-authored task prompts) intact for audit and
statistical integrity.

Erasure redacts every top-level PII-bearing column this pass identified:
resume filename/email/full_text, the extracted PII fields' value *and*
source_quote (a security review of this module caught that source_quote
was initially missed — same row, same field, easy to overlook), invite/
session emails, questionnaire answers, turn answers, candidate-authored
code/discussion content, and the evaluation payload's embedded email.

Known limitation, documented rather than silently ignored: JSONB evidence
payloads that embed literal resume quotes further downstream
(`scoring_runs.checks_payload`/`dimensions_payload`, produced by the
scoring pipeline from the same source text) are not deep-redacted by this
pass. A future pass would need to walk those payloads' embedded
source_quote/rationale strings too.

`POST /retention/run` (M12) drives the same erasure logic automatically,
without a specific candidate email, against every candidate whose most
recent activity in this organization predates a retention cutoff — see
`retention.py`.
"""

import hashlib
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_app_settings, get_db, require_roles
from app.dsar_service import (
    apply_erasure,
    find_candidate_records,
    questionnaire_titles_for,
    record_counts,
)
from app.models import Role, User, utcnow
from app.retention import run_retention_sweep
from app.settings import Settings
from app.validation import EmailAddress

router = APIRouter(tags=["dsar"])

DSAR_ROLES = (Role.ADMIN.value,)


class DsarExportRequest(BaseModel):
    email: EmailAddress


@router.post("/dsar/export")
async def export_candidate_data(
    body: DsarExportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*DSAR_ROLES)),
) -> dict[str, object]:
    # POST with the email in the body, not a GET query parameter: a query
    # string is exactly what reverse-proxy/access logs capture by default,
    # which would leak the raw candidate email into logs the DSAR flow is
    # otherwise careful to keep it out of (the audit event below only ever
    # stores its SHA-256 hash). Matches DsarEraseRequest's shape below.
    email = body.email
    records = await find_candidate_records(db, user.organization_id, email)

    if not any(records.values()):
        raise HTTPException(status_code=404, detail="No records found for this email")

    questionnaire_titles = await questionnaire_titles_for(db, records["invites"])

    await record_event(
        db,
        action="dsar.exported",
        entity_type="candidate",
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={
            "candidate_email_sha256": hashlib.sha256(
                email.strip().lower().encode("utf-8")
            ).hexdigest(),
            "record_counts": record_counts(records),
        },
    )

    return {
        "resumes": [
            {
                "id": str(r.id),
                "filename": r.filename,
                "candidate_email": r.candidate_email,
                "full_text": r.full_text,
                "created_at": r.created_at.isoformat(),
            }
            for r in records["resumes"]
        ],
        "extracted_fields": [
            {"field_name": f.field_name, "value": f.value, "confidence": f.confidence}
            for f in records["fields"]
        ],
        "questionnaire_invites": [
            {
                "questionnaire_title": questionnaire_titles.get(i.questionnaire_id, "unknown"),
                "candidate_email": i.candidate_email,
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
            }
            for i in records["invites"]
        ],
        "questionnaire_responses": [
            {"answers": r.answers, "submitted": r.submitted} for r in records["responses"]
        ],
        "interview_sessions": [
            {
                "id": str(s.id),
                "candidate_email": s.candidate_email,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in records["sessions"]
        ],
        "interview_turns": [
            {"question_text": t.question_text, "answer_text": t.answer_text}
            for t in records["turns"]
        ],
        "interview_consents": [
            {"granted": c.granted, "decided_at": c.decided_at.isoformat()}
            for c in records["consents"]
        ],
        "coding_tasks": [{"title": t.title, "language": t.language} for t in records["tasks"]],
        "code_snapshots": [{"source": s.source} for s in records["snapshots"]],
        "code_executions": [
            {"source": e.source, "stdout": e.stdout, "stderr": e.stderr}
            for e in records["executions"]
        ],
        "discussion_messages": [
            {"author": m.author, "body": m.body}
            for m in records["messages"]
            if m.author == "candidate"
        ],
        "evaluation_reports": [
            {"overall_score": e.overall_score, "verdict": e.verdict} for e in records["evaluations"]
        ],
        "record_counts": record_counts(records),
    }


class DsarEraseRequest(BaseModel):
    email: EmailAddress
    confirm: bool


@router.post("/dsar/erase")
async def erase_candidate_data(
    body: DsarEraseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*DSAR_ROLES)),
) -> dict[str, object]:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to proceed")

    records = await find_candidate_records(db, user.organization_id, body.email)
    if not any(records.values()):
        raise HTTPException(status_code=404, detail="No records found for this email")

    counts = apply_erasure(records)
    await record_event(
        db,
        action="dsar.erased",
        entity_type="candidate",
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={
            "candidate_email_sha256": hashlib.sha256(
                body.email.strip().lower().encode("utf-8")
            ).hexdigest(),
            "record_counts": counts,
        },
    )
    await db.flush()
    return {"erased": True, "record_counts": counts}


class RetentionRunRequest(BaseModel):
    # Overrides the organization-wide AIVA_RETENTION_DAYS default for this run
    # only — lets an admin run a tighter one-off sweep (or, in tests, an
    # immediate one via 0) without changing the standing policy.
    retention_days: int | None = Field(default=None, ge=0)


@router.post("/retention/run")
async def run_retention(
    request: Request,
    body: RetentionRunRequest = RetentionRunRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*DSAR_ROLES)),
) -> dict[str, object]:
    settings: Settings = get_app_settings(request)
    retention_days = (
        body.retention_days if body.retention_days is not None else settings.retention_days
    )
    cutoff = utcnow() - timedelta(days=retention_days)

    result = await run_retention_sweep(db, user.organization_id, cutoff)
    await record_event(
        db,
        action="retention.swept",
        entity_type="candidate",
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"retention_days": retention_days, **result},
    )
    await db.flush()
    return result


__all__ = ["router"]
