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
"""

import hashlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_db, require_roles
from app.models import (
    CodeExecution,
    CodeSnapshot,
    CodingTask,
    DiscussionMessage,
    EvaluationReport,
    ExtractedFieldRow,
    InterviewConsent,
    InterviewSession,
    InterviewTurn,
    Questionnaire,
    QuestionnaireInvite,
    QuestionnaireResponse,
    ResumeDocument,
    Role,
    User,
    WhiteboardStroke,
)
from app.validation import EmailAddress

router = APIRouter(tags=["dsar"])

DSAR_ROLES = (Role.ADMIN.value,)
REDACTED = "[redacted per DSAR erasure request]"
PII_FIELD_NAMES = frozenset({"email", "phone", "name", "full_name", "linkedin"})


async def _all(db: AsyncSession, stmt: Any) -> list[Any]:
    return list((await db.execute(stmt)).scalars().all())


async def _find_candidate_records(
    db: AsyncSession, organization_id: uuid.UUID, email: str
) -> dict[str, list[Any]]:
    normalized = email.strip().lower()

    resumes = await _all(
        db,
        select(ResumeDocument).where(
            ResumeDocument.organization_id == organization_id,
            func.lower(ResumeDocument.candidate_email) == normalized,
        ),
    )
    resume_ids = [r.id for r in resumes]

    fields = (
        await _all(db, select(ExtractedFieldRow).where(ExtractedFieldRow.resume_id.in_(resume_ids)))
        if resume_ids
        else []
    )

    invites = await _all(
        db,
        select(QuestionnaireInvite).where(
            QuestionnaireInvite.organization_id == organization_id,
            func.lower(QuestionnaireInvite.candidate_email) == normalized,
        ),
    )
    invite_ids = [i.id for i in invites]
    responses = (
        await _all(
            db, select(QuestionnaireResponse).where(QuestionnaireResponse.invite_id.in_(invite_ids))
        )
        if invite_ids
        else []
    )

    sessions = await _all(
        db,
        select(InterviewSession).where(
            InterviewSession.organization_id == organization_id,
            func.lower(InterviewSession.candidate_email) == normalized,
        ),
    )
    session_ids = [s.id for s in sessions]

    async def _by_session(model: Any) -> list[Any]:
        if not session_ids:
            return []
        return await _all(db, select(model).where(model.session_id.in_(session_ids)))

    turns = await _by_session(InterviewTurn)
    consents = await _by_session(InterviewConsent)
    tasks = await _by_session(CodingTask)
    task_ids = [t.id for t in tasks]
    snapshots = (
        await _all(db, select(CodeSnapshot).where(CodeSnapshot.task_id.in_(task_ids)))
        if task_ids
        else []
    )
    executions = (
        await _all(db, select(CodeExecution).where(CodeExecution.task_id.in_(task_ids)))
        if task_ids
        else []
    )
    strokes = await _by_session(WhiteboardStroke)
    messages = await _by_session(DiscussionMessage)

    evaluations = (
        await _all(
            db,
            select(EvaluationReport).where(
                EvaluationReport.organization_id == organization_id,
                EvaluationReport.resume_id.in_(resume_ids),
            ),
        )
        if resume_ids
        else []
    )

    return {
        "resumes": resumes,
        "fields": fields,
        "invites": invites,
        "responses": responses,
        "sessions": sessions,
        "turns": turns,
        "consents": consents,
        "tasks": tasks,
        "snapshots": snapshots,
        "executions": executions,
        "strokes": strokes,
        "messages": messages,
        "evaluations": evaluations,
    }


def _record_counts(records: dict[str, list[Any]]) -> dict[str, int]:
    return {name: len(rows) for name, rows in records.items()}


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
    records = await _find_candidate_records(db, user.organization_id, email)

    if not any(records.values()):
        raise HTTPException(status_code=404, detail="No records found for this email")

    questionnaire_titles: dict[uuid.UUID, str] = {}
    if records["invites"]:
        questionnaires = (
            (
                await db.execute(
                    select(Questionnaire).where(
                        Questionnaire.id.in_([i.questionnaire_id for i in records["invites"]])
                    )
                )
            )
            .scalars()
            .all()
        )
        questionnaire_titles = {q.id: q.title for q in questionnaires}

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
            "record_counts": _record_counts(records),
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
        "record_counts": _record_counts(records),
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

    records = await _find_candidate_records(db, user.organization_id, body.email)
    if not any(records.values()):
        raise HTTPException(status_code=404, detail="No records found for this email")

    for resume in records["resumes"]:
        resume.candidate_email = None
        resume.full_text = REDACTED
        resume.filename = REDACTED
    for field in records["fields"]:
        if field.field_name in PII_FIELD_NAMES:
            field.value = REDACTED
            field.source_quote = REDACTED
    for invite in records["invites"]:
        invite.candidate_email = f"redacted-{invite.id.hex}@invalid.example"
    for response in records["responses"]:
        response.answers = {}
        response.history = []
    for session in records["sessions"]:
        session.candidate_email = f"redacted-{session.id.hex}@invalid.example"
    for turn in records["turns"]:
        if turn.answer_text is not None:
            turn.answer_text = REDACTED
    for snapshot in records["snapshots"]:
        snapshot.source = REDACTED
    for execution in records["executions"]:
        execution.source = REDACTED
        execution.stdin = REDACTED
        execution.stdout = REDACTED
        execution.stderr = REDACTED
    for message in records["messages"]:
        if message.author == "candidate":
            message.body = REDACTED
            message.author_label = REDACTED
    for evaluation in records["evaluations"]:
        evaluation.payload = {**evaluation.payload, "candidate_email": REDACTED}

    counts = _record_counts(records)
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


__all__ = ["router"]
