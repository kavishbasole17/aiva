"""Shared candidate-record lookup and PII erasure logic.

Extracted from `routers_dsar.py` so the same "find every record tied to a
candidate's email, then redact the PII-bearing columns in place" logic can
be driven either by a manual, admin-initiated DSAR request or by an
automated retention sweep (`retention.py`) without duplicating either half.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    WhiteboardStroke,
)

REDACTED = "[redacted per DSAR erasure request]"
PII_FIELD_NAMES = frozenset({"email", "phone", "name", "full_name", "linkedin"})


async def _all(db: AsyncSession, stmt: Any) -> list[Any]:
    return list((await db.execute(stmt)).scalars().all())


async def find_candidate_records(
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


def record_counts(records: dict[str, list[Any]]) -> dict[str, int]:
    return {name: len(rows) for name, rows in records.items()}


async def questionnaire_titles_for(
    db: AsyncSession, invites: list[QuestionnaireInvite]
) -> dict[uuid.UUID, str]:
    if not invites:
        return {}
    questionnaires = await _all(
        db, select(Questionnaire).where(Questionnaire.id.in_([i.questionnaire_id for i in invites]))
    )
    return {q.id: q.title for q in questionnaires}


def apply_erasure(records: dict[str, list[Any]]) -> dict[str, int]:
    """Redact every PII-bearing column across an already-fetched record set.

    Never deletes rows (scores/verdicts/non-PII content stay intact for audit
    and statistical integrity) — same discipline as every other append-only
    table in this codebase.
    """
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

    return record_counts(records)


__all__ = [
    "PII_FIELD_NAMES",
    "REDACTED",
    "apply_erasure",
    "find_candidate_records",
    "questionnaire_titles_for",
    "record_counts",
]
