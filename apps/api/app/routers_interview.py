"""Interview sessions: consent gate, device pre-check, adaptive STT/TTS loop.

Staff endpoints create tokenised single-use sessions (raw join token shown
once, only its SHA-256 stored — same discipline as questionnaire invites and
refresh tokens). Public endpoints are gated purely by possession of that raw
token and drive the candidate-side lifecycle:

    pending_consent → consent_granted → precheck_passed → active → completed

Every gate fails closed: no interview turn is served without granted consent
at the current statement version, a passed device pre-check, and a non-expired
non-terminal session (expired → 410, wrong state → 409). Transcripts persist
per turn with STT/TTS model attribution so any answer can be replayed through
the engine to the same outcome.
"""

import base64
import binascii
import hashlib
import uuid
from datetime import timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_app_settings, get_db, require_roles
from app.interview_engine import InterviewPlan, TurnKind, build_plan, decide
from app.matching import skills_present, stated_years
from app.models import (
    ExtractedFieldRow,
    InterviewConsent,
    InterviewSession,
    InterviewSessionStatus,
    InterviewSlot,
    InterviewTurn,
    JobDescription,
    ResumeDocument,
    Role,
    User,
    utcnow,
)
from app.precheck import PRECHECK_SUITE_VERSION, PreCheckReport, evaluate_precheck
from app.questionnaire_service import generate_invite_token, hash_token
from app.rate_limit import PUBLIC_ENDPOINT_LIMIT, limiter
from app.settings import Settings

router = APIRouter(tags=["interviews"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)

CONSENT_TEXT_VERSION = "2026.08-v1"
CONSENT_STATEMENT = (
    "I consent to this interview being recorded and transcribed, and to automated "
    "processing of my answers together with my submitted resume for hiring "
    "evaluation by this organization. I understand I can withdraw at any time by "
    "ending the session, after which recorded material will be handled per the "
    "organization's retention policy."
)


class SessionCreate(BaseModel):
    resume_id: str | None = None


class ConsentDecision(BaseModel):
    accepted_version: str = PydField(min_length=1, max_length=32)
    granted: bool


class TurnAnswer(BaseModel):
    answer_text: str | None = PydField(default=None, max_length=8000)
    audio_b64: str | None = PydField(default=None, max_length=15_000_000)


class TtsRequest(BaseModel):
    text: str = PydField(min_length=1, max_length=4000)


class ExtractedFieldLike:
    def __init__(self, field_name: str, value: str) -> None:
        self.field_name = field_name
        self.value = value


def _terminal(status: str) -> bool:
    return status in {
        InterviewSessionStatus.COMPLETED.value,
        InterviewSessionStatus.DECLINED.value,
        InterviewSessionStatus.ABORTED.value,
    }


async def _session_by_token(db: AsyncSession, raw_token: str) -> InterviewSession:
    session = (
        await db.execute(
            select(InterviewSession).where(InterviewSession.token_hash == hash_token(raw_token))
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    if session.expires_at < utcnow() and not _terminal(session.status):
        raise HTTPException(status_code=410, detail="Interview invitation expired")
    return session


def _plan_of(session: InterviewSession) -> InterviewPlan:
    try:
        return InterviewPlan.model_validate(session.plan_payload)
    except Exception as exc:  # pragma: no cover - plan is written only by this module
        raise HTTPException(status_code=500, detail="Corrupt interview plan") from exc


def _asked_history(session: InterviewSession) -> list[tuple[str, str]]:
    history: list[tuple[str, str]] = []
    for entry in session.asked_turns:
        kind = str(entry.get("kind", ""))
        topic_id = str(entry.get("topic_id", ""))
        if kind:
            history.append((kind, topic_id))
    return history


async def _build_plan_for(
    db: AsyncSession,
    requisition_id: uuid.UUID,
    resume_id: uuid.UUID | None,
) -> InterviewPlan:
    jd = (
        await db.execute(
            select(JobDescription)
            .where(JobDescription.requisition_id == requisition_id)
            .order_by(JobDescription.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    required: list[str] = list(jd.required_skills) if jd else []
    min_years: int = jd.min_years_experience if jd else 0

    present: set[str] = set()
    claimed_years: int | None = None
    if resume_id is not None:
        field_rows = (
            (
                await db.execute(
                    select(ExtractedFieldRow).where(ExtractedFieldRow.resume_id == resume_id)
                )
            )
            .scalars()
            .all()
        )
        fields = [ExtractedFieldLike(row.field_name, row.value) for row in field_rows]
        present = skills_present(fields)
        claimed_years = stated_years(fields)

    missing = [s for s in required if s.lower() not in present]
    verified = [s for s in required if s.lower() in present]
    return build_plan(
        requisition_id=str(requisition_id),
        role_title=jd.title if jd else "this role",
        required_skills=verified or required[:2],
        missing_skills=missing,
        min_years_experience=min_years,
        stated_years=claimed_years,
    )


@router.post("/slots/{slot_id}/interview-session", status_code=201)
async def create_session(
    slot_id: uuid.UUID,
    body: SessionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    settings: Settings = get_app_settings(request)
    slot = (
        await db.execute(select(InterviewSlot).where(InterviewSlot.id == slot_id))
    ).scalar_one_or_none()
    if slot is None or slot.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot.status != "booked" or not slot.booked_for_email:
        raise HTTPException(status_code=409, detail="Slot must be booked before creating a session")

    from app.routers_resume import _load_requisition as _load_scoped_requisition

    await _load_scoped_requisition(db, user, slot.requisition_id)

    resume_id: uuid.UUID | None = None
    if body.resume_id:
        try:
            resume_id = uuid.UUID(body.resume_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="resume_id must be a UUID") from exc
        resume = (
            await db.execute(select(ResumeDocument).where(ResumeDocument.id == resume_id))
        ).scalar_one_or_none()
        if resume is None or resume.organization_id != user.organization_id:
            raise HTTPException(status_code=404, detail="Resume not found")
    else:
        latest = (
            await db.execute(
                select(ResumeDocument.id)
                .where(
                    ResumeDocument.requisition_id == slot.requisition_id,
                    ResumeDocument.candidate_email == slot.booked_for_email,
                )
                .order_by(ResumeDocument.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        resume_id = latest

    plan = await _build_plan_for(db, slot.requisition_id, resume_id)
    raw, digest = generate_invite_token()
    session_row = InterviewSession(
        organization_id=user.organization_id,
        requisition_id=slot.requisition_id,
        slot_id=slot.id,
        resume_id=resume_id,
        candidate_email=slot.booked_for_email,
        token_hash=digest,
        status=InterviewSessionStatus.PENDING_CONSENT.value,
        plan_payload=plan.model_dump(),
        plan_fingerprint=plan.plan_fingerprint,
        expires_at=utcnow() + timedelta(hours=settings.interview_token_hours),
    )
    db.add(session_row)
    await db.flush()
    await record_event(
        db,
        action="interview.session_created",
        entity_type="interview_session",
        entity_id=session_row.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={
            "candidate_email": session_row.candidate_email,
            "plan_fingerprint": plan.plan_fingerprint,
            "topic_count": len(plan.topics),
        },
    )
    return {
        "id": str(session_row.id),
        "token": raw,
        "expires_at": session_row.expires_at.isoformat(),
        "plan_fingerprint": plan.plan_fingerprint,
        "topic_count": len(plan.topics),
    }


@router.get("/requisitions/{requisition_id}/interview-sessions")
async def list_sessions(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    from app.routers_resume import _load_requisition as _load_scoped_requisition

    await _load_scoped_requisition(db, user, requisition_id)
    rows = (
        (
            await db.execute(
                select(InterviewSession)
                .where(InterviewSession.requisition_id == requisition_id)
                .order_by(InterviewSession.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "sessions": [
            {
                "id": str(row.id),
                "candidate_email": row.candidate_email,
                "status": row.status,
                "precheck_passed": row.precheck_passed,
                "turn_count": len(row.asked_turns),
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "expires_at": row.expires_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.get("/interview-sessions/{session_id}")
async def get_session_detail(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = (
        await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    ).scalar_one_or_none()
    if session is None or session.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Session not found")
    turns = (
        (
            await db.execute(
                select(InterviewTurn)
                .where(InterviewTurn.session_id == session.id)
                .order_by(InterviewTurn.sequence)
            )
        )
        .scalars()
        .all()
    )
    consents = (
        (
            await db.execute(
                select(InterviewConsent)
                .where(InterviewConsent.session_id == session.id)
                .order_by(InterviewConsent.decided_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(session.id),
        "candidate_email": session.candidate_email,
        "status": session.status,
        "plan_fingerprint": session.plan_fingerprint,
        "precheck_report": session.precheck_report,
        "precheck_passed": session.precheck_passed,
        "turns": [
            {
                "sequence": turn.sequence,
                "kind": turn.kind,
                "topic_id": turn.topic_id,
                "question_text": turn.question_text,
                "answer_text": turn.answer_text,
                "stt_confidence": turn.stt_confidence,
                "stt_model_id": turn.stt_model_id,
                "tts_model_id": turn.tts_model_id,
                "answer_audio_sha256": turn.answer_audio_sha256,
            }
            for turn in turns
        ],
        "consents": [
            {
                "granted": consent.granted,
                "consent_text_version": consent.consent_text_version,
                "decided_at": consent.decided_at.isoformat(),
            }
            for consent in consents
        ],
    }


async def _open_question(db: AsyncSession, session: InterviewSession) -> InterviewTurn | None:
    return (
        await db.execute(
            select(InterviewTurn)
            .where(
                InterviewTurn.session_id == session.id,
                InterviewTurn.answer_text.is_(None),
            )
            .order_by(InterviewTurn.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/public/interview-sessions/{raw_token}")
@limiter.limit(PUBLIC_ENDPOINT_LIMIT)
async def public_session_state(
    request: Request, raw_token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    open_turn = None if _terminal(session.status) else await _open_question(db, session)
    return {
        "status": session.status,
        "candidate_email": session.candidate_email,
        "expires_at": session.expires_at.isoformat(),
        "consent": {
            "required": session.status == InterviewSessionStatus.PENDING_CONSENT.value,
            "version": CONSENT_TEXT_VERSION,
            "statement": CONSENT_STATEMENT,
        },
        "precheck": {
            "suite_version": PRECHECK_SUITE_VERSION,
            "passed": session.precheck_passed,
            "report": session.precheck_report,
        },
        "progress": {
            "asked_turns": len(_asked_history(session)),
            "plan_fingerprint": session.plan_fingerprint,
        },
        "open_question": (
            {
                "kind": open_turn.kind,
                "topic_id": open_turn.topic_id,
                "text": open_turn.question_text,
            }
            if open_turn is not None and open_turn.kind != TurnKind.CLOSING.value
            else None
        ),
    }


@router.post("/public/interview-sessions/{raw_token}/consent")
async def decide_consent(
    raw_token: str,
    body: ConsentDecision,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    if session.status != InterviewSessionStatus.PENDING_CONSENT.value:
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")
    if body.accepted_version != CONSENT_TEXT_VERSION:
        raise HTTPException(
            status_code=400,
            detail={"error": "stale_consent_version", "expected": CONSENT_TEXT_VERSION},
        )

    db.add(
        InterviewConsent(
            organization_id=session.organization_id,
            session_id=session.id,
            granted=body.granted,
            consent_text_version=body.accepted_version,
            statement_snapshot=CONSENT_STATEMENT,
        )
    )
    if not body.granted:
        session.status = InterviewSessionStatus.DECLINED.value
        session.finished_at = utcnow()
        await record_event(
            db,
            action="interview.consent_declined",
            entity_type="interview_session",
            entity_id=session.id,
            organization_id=session.organization_id,
        )
        await db.flush()
        return {"status": session.status}

    session.status = InterviewSessionStatus.CONSENT_GRANTED.value
    await record_event(
        db,
        action="interview.consent_granted",
        entity_type="interview_session",
        entity_id=session.id,
        organization_id=session.organization_id,
        payload={"consent_text_version": CONSENT_TEXT_VERSION},
    )
    await db.flush()
    return {"status": session.status}


@router.post("/public/interview-sessions/{raw_token}/precheck")
async def submit_precheck(
    raw_token: str,
    body: PreCheckReport,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    if session.status not in {
        InterviewSessionStatus.CONSENT_GRANTED.value,
        InterviewSessionStatus.PRECHECK_PASSED.value,
    }:
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")

    result = evaluate_precheck(body)
    session.precheck_report = {**body.model_dump(), "failures": result.failures}
    session.precheck_passed = result.passed
    if result.passed:
        session.status = InterviewSessionStatus.PRECHECK_PASSED.value
        await record_event(
            db,
            action="interview.precheck_passed",
            entity_type="interview_session",
            entity_id=session.id,
            organization_id=session.organization_id,
        )
    elif session.status == InterviewSessionStatus.PRECHECK_PASSED.value:
        # A later failing re-check must revoke the previously unlocked gate.
        session.status = InterviewSessionStatus.CONSENT_GRANTED.value
    await db.flush()
    return {"passed": result.passed, "failures": result.failures}


@router.post("/public/interview-sessions/{raw_token}/start")
async def start_interview(
    raw_token: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    if session.status != InterviewSessionStatus.PRECHECK_PASSED.value:
        raise HTTPException(
            status_code=409,
            detail="Interview requires granted consent and a passed pre-check first",
        )
    plan = _plan_of(session)
    decision = decide(plan, [], "")
    session.status = InterviewSessionStatus.ACTIVE.value
    session.started_at = utcnow()
    session.asked_turns = [{"kind": decision.kind.value, "topic_id": decision.topic_id or ""}]
    db.add(
        InterviewTurn(
            organization_id=session.organization_id,
            session_id=session.id,
            sequence=0,
            kind=decision.kind.value,
            topic_id=decision.topic_id,
            question_text=decision.prompt,
        )
    )
    await record_event(
        db,
        action="interview.started",
        entity_type="interview_session",
        entity_id=session.id,
        organization_id=session.organization_id,
        payload={"plan_fingerprint": session.plan_fingerprint},
    )
    await db.flush()
    return {
        "status": session.status,
        "question": {
            "kind": decision.kind.value,
            "topic_id": decision.topic_id,
            "text": decision.prompt,
            "tts_text": decision.tts_text,
        },
        "progress_total": decision.progress_total,
    }


async def _transcribe(settings: Settings, audio_b64: str) -> tuple[str, float, str, str]:
    """Return (transcript, confidence, model_id, audio_sha256) via the gateway."""
    if not settings.ai_gateway_url:
        raise HTTPException(status_code=503, detail="AI gateway URL is not configured")
    try:
        decoded = base64.b64decode(audio_b64, validate=True)
        audio_sha = hashlib.sha256(decoded).hexdigest()
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="audio_b64 is not valid base64") from exc
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post("/v1/stt", json={"audio_b64": audio_b64})
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"AI gateway unreachable: {exc}") from exc
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=422, detail="Transcription produced no speech")
    return text, float(payload.get("confidence", 0.0)), str(payload.get("model_id")), audio_sha


@router.post("/public/interview-sessions/{raw_token}/turns")
async def submit_turn(
    raw_token: str,
    body: TurnAnswer,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    settings: Settings = get_app_settings(request)
    session = await _session_by_token(db, raw_token)
    if session.status != InterviewSessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")

    open_turn = await _open_question(db, session)
    if open_turn is None or open_turn.kind == TurnKind.CLOSING.value:
        raise HTTPException(status_code=409, detail="No open question awaiting an answer")

    stt_confidence: float | None = None
    stt_model: str | None = None
    audio_sha: str | None = None
    if body.audio_b64 is not None:
        transcript, stt_confidence, stt_model, audio_sha = await _transcribe(
            settings, body.audio_b64
        )
        answer_text: str = transcript
    elif body.answer_text is not None and body.answer_text.strip():
        answer_text = body.answer_text.strip()
    else:
        raise HTTPException(status_code=400, detail="Provide answer_text or audio_b64")

    open_turn.answer_text = answer_text
    open_turn.stt_confidence = stt_confidence
    open_turn.stt_model_id = stt_model
    open_turn.answer_audio_sha256 = audio_sha

    plan = _plan_of(session)
    asked = _asked_history(session)
    decision = decide(plan, asked, answer_text)

    if decision.kind == TurnKind.CLOSING:
        session.status = InterviewSessionStatus.COMPLETED.value
        session.finished_at = utcnow()
        db.add(
            InterviewTurn(
                organization_id=session.organization_id,
                session_id=session.id,
                sequence=open_turn.sequence + 1,
                kind=decision.kind.value,
                topic_id=None,
                question_text=decision.prompt,
            )
        )
        await record_event(
            db,
            action="interview.completed",
            entity_type="interview_session",
            entity_id=session.id,
            organization_id=session.organization_id,
            payload={"turns": len(asked) + 1},
        )
    else:
        session.asked_turns = [
            *session.asked_turns,
            {"kind": decision.kind.value, "topic_id": decision.topic_id or ""},
        ]
        db.add(
            InterviewTurn(
                organization_id=session.organization_id,
                session_id=session.id,
                sequence=open_turn.sequence + 1,
                kind=decision.kind.value,
                topic_id=decision.topic_id,
                question_text=decision.prompt,
            )
        )

    await db.flush()
    return {
        "status": session.status,
        "transcript": {"text": answer_text},
        "stt": {"confidence": stt_confidence, "model_id": stt_model} if stt_model else None,
        "next": {
            "kind": decision.kind.value,
            "topic_id": decision.topic_id,
            "text": decision.prompt,
            "tts_text": decision.tts_text,
        },
        "completed": session.status == InterviewSessionStatus.COMPLETED.value,
    }


@router.post("/public/interview-sessions/{raw_token}/finish")
async def finish_interview(
    raw_token: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    if session.status != InterviewSessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")
    session.status = InterviewSessionStatus.ABORTED.value
    session.finished_at = utcnow()
    await record_event(
        db,
        action="interview.aborted",
        entity_type="interview_session",
        entity_id=session.id,
        organization_id=session.organization_id,
    )
    await db.flush()
    return {"status": session.status}


@router.post("/public/interview-sessions/{raw_token}/tts")
async def speak(
    raw_token: str,
    body: TtsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    if _terminal(session.status):
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")
    settings: Settings = get_app_settings(request)
    if not settings.ai_gateway_url:
        raise HTTPException(status_code=503, detail="AI gateway URL is not configured")
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post("/v1/tts", json={"text": body.text})
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"AI gateway unreachable: {exc}") from exc
    return payload


__all__ = ["CONSENT_STATEMENT", "CONSENT_TEXT_VERSION", "router"]
