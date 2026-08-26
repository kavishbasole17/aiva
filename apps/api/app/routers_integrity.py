"""M11 integrity signals: browser-reported focus/visibility events during an
active interview.

Deliberately scoped to zero-ML-dependency signals — see migration
0012_integrity_signals and ADR-023 for why face/gaze-based proctoring
(InsightFace/MediaPipe) stays deferred to GPU deployment rather than being
mocked here: unlike STT/TTS/embeddings, there's no frame-capture pipeline
in the candidate app to mock a backend *for* yet, so a mock analyzer would
just be inventing input, not standing in for a real one. Tab-blur/
visibility/fullscreen-exit events are real signals a browser can report
today with no model at all.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_roles
from app.models import IntegritySignal, InterviewSession, InterviewSessionStatus, Role, User
from app.routers_interview import _session_by_token

router = APIRouter(tags=["integrity"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)

SUPPORTED_SIGNAL_TYPES = frozenset(
    {"tab_blur", "tab_focus", "visibility_hidden", "visibility_visible", "fullscreen_exit"}
)


class IntegritySignalCreate(BaseModel):
    signal_type: str
    detail: dict[str, object] = PydField(default_factory=dict)


def _signal_view(row: IntegritySignal) -> dict[str, object]:
    return {
        "id": str(row.id),
        "signal_type": row.signal_type,
        "detail": row.detail,
        "created_at": row.created_at.isoformat(),
    }


@router.post("/public/interview-sessions/{raw_token}/integrity-signals", status_code=201)
async def report_integrity_signal(
    raw_token: str,
    body: IntegritySignalCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    if session.status != InterviewSessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")
    if body.signal_type not in SUPPORTED_SIGNAL_TYPES:
        raise HTTPException(
            status_code=400, detail=f"signal_type must be one of {sorted(SUPPORTED_SIGNAL_TYPES)}"
        )
    row = IntegritySignal(
        organization_id=session.organization_id,
        session_id=session.id,
        signal_type=body.signal_type,
        detail=body.detail,
    )
    db.add(row)
    await db.flush()
    return _signal_view(row)


@router.get("/interview-sessions/{session_id}/integrity-signals")
async def list_integrity_signals(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = (
        await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    ).scalar_one_or_none()
    if session is None or session.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Session not found")

    rows = (
        (
            await db.execute(
                select(IntegritySignal)
                .where(IntegritySignal.session_id == session_id)
                .order_by(IntegritySignal.created_at)
            )
        )
        .scalars()
        .all()
    )
    summary = {
        str(kind): count
        for kind, count in (
            await db.execute(
                select(IntegritySignal.signal_type, func.count())
                .where(IntegritySignal.session_id == session_id)
                .group_by(IntegritySignal.signal_type)
            )
        ).all()
    }
    return {"signals": [_signal_view(row) for row in rows], "summary": summary}


__all__ = ["router"]
