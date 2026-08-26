"""M9 live-coding workspace: tasks, autosaved editor state, sandboxed runs,
whiteboard, and task discussion, layered onto an active interview session.

Same two-sided shape as routers_interview.py: staff endpoints (JWT, ownership
checked against the session's organization) create tasks and can watch/
annotate everything; public endpoints (raw-token, candidate side) do the
actual editing, running, drawing, and messaging. Candidate write actions are
gated to an ACTIVE session — same discipline as submitting a turn answer —
so nothing can be edited before consent+pre-check clear or after the
interview ends; reads stay open through any non-terminal state so a reload
mid-session doesn't lose the picture.

Screen share has no backend: it needs real WebRTC/LiveKit infrastructure
this compose stack doesn't run (same class of gap M8 documented for
STT/TTS GPU models — the mock-now/hardened-at-deployment precedent). The
stub below raises a clear 501 rather than pretending to work.
"""

import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_app_settings, get_db, require_roles
from app.models import (
    CodeExecution,
    CodeSnapshot,
    CodingTask,
    DiscussionMessage,
    InterviewSession,
    InterviewSessionStatus,
    Role,
    User,
    WhiteboardStroke,
)
from app.routers_interview import _session_by_token, _terminal
from app.settings import Settings

router = APIRouter(tags=["workspace"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)

SUPPORTED_LANGUAGES = ("python", "javascript")
MAX_SOURCE_LEN = 65_536
MAX_STROKE_PAYLOAD_LEN = 200_000


class TaskCreate(BaseModel):
    title: str = PydField(min_length=1, max_length=200)
    prompt: str = PydField(min_length=1, max_length=4000)
    starter_code: str = PydField(default="", max_length=MAX_SOURCE_LEN)
    language: str


class CodeSave(BaseModel):
    source: str = PydField(max_length=MAX_SOURCE_LEN)


class RunRequest(BaseModel):
    source: str = PydField(max_length=MAX_SOURCE_LEN)
    stdin: str = PydField(default="", max_length=MAX_SOURCE_LEN)


class StrokeCreate(BaseModel):
    stroke_payload: dict[str, Any]


class MessageCreate(BaseModel):
    body: str = PydField(min_length=1, max_length=4000)


def _task_view(task: CodingTask) -> dict[str, object]:
    return {
        "id": str(task.id),
        "title": task.title,
        "prompt": task.prompt,
        "starter_code": task.starter_code,
        "language": task.language,
        "created_at": task.created_at.isoformat(),
    }


def _execution_view(row: CodeExecution) -> dict[str, object]:
    return {
        "id": str(row.id),
        "stdout": row.stdout,
        "stderr": row.stderr,
        "exit_code": row.exit_code,
        "timed_out": row.timed_out,
        "truncated": row.truncated,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at.isoformat(),
    }


def _stroke_view(row: WhiteboardStroke) -> dict[str, object]:
    return {
        "id": str(row.id),
        "author": row.author,
        "stroke_payload": row.stroke_payload,
        "created_at": row.created_at.isoformat(),
    }


def _message_view(row: DiscussionMessage) -> dict[str, object]:
    return {
        "id": str(row.id),
        "task_id": str(row.task_id) if row.task_id else None,
        "author": row.author,
        "author_label": row.author_label,
        "body": row.body,
        "created_at": row.created_at.isoformat(),
    }


async def _staff_session(db: AsyncSession, user: User, session_id: uuid.UUID) -> InterviewSession:
    session = (
        await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    ).scalar_one_or_none()
    if session is None or session.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _staff_task(
    db: AsyncSession, session: InterviewSession, task_id: uuid.UUID
) -> CodingTask:
    task = (
        await db.execute(select(CodingTask).where(CodingTask.id == task_id))
    ).scalar_one_or_none()
    if task is None or task.session_id != session.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _latest_snapshot(db: AsyncSession, task_id: uuid.UUID) -> CodeSnapshot | None:
    return (
        await db.execute(
            select(CodeSnapshot)
            .where(CodeSnapshot.task_id == task_id)
            .order_by(CodeSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _execute_via_sandbox(
    settings: Settings, language: str, source: str, stdin: str
) -> dict[str, Any]:
    if not settings.sandbox_url:
        raise HTTPException(status_code=503, detail="Sandbox URL is not configured")
    try:
        async with httpx.AsyncClient(base_url=settings.sandbox_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/execute",
                json={"language": language, "source": source, "stdin": stdin},
            )
            if response.status_code == 400:
                raise HTTPException(status_code=400, detail=response.json().get("detail"))
            if response.status_code == 503:
                raise HTTPException(status_code=503, detail=response.json().get("detail"))
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Sandbox runner unreachable: {exc}") from exc


# ---------------------------------------------------------------------------
# Staff endpoints
# ---------------------------------------------------------------------------


@router.post("/interview-sessions/{session_id}/coding-tasks", status_code=201)
async def create_task(
    session_id: uuid.UUID,
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400, detail=f"language must be one of {SUPPORTED_LANGUAGES}"
        )
    task = CodingTask(
        organization_id=session.organization_id,
        session_id=session.id,
        title=body.title,
        prompt=body.prompt,
        starter_code=body.starter_code,
        language=body.language,
    )
    db.add(task)
    await db.flush()
    db.add(
        CodeSnapshot(
            organization_id=session.organization_id, task_id=task.id, source=body.starter_code
        )
    )
    await record_event(
        db,
        action="workspace.task_created",
        entity_type="coding_task",
        entity_id=task.id,
        actor_id=user.id,
        organization_id=session.organization_id,
        payload={"language": task.language, "session_id": str(session.id)},
    )
    await db.flush()
    return _task_view(task)


@router.get("/interview-sessions/{session_id}/coding-tasks")
async def list_tasks_staff(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    rows = (
        (
            await db.execute(
                select(CodingTask)
                .where(CodingTask.session_id == session.id)
                .order_by(CodingTask.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"tasks": [_task_view(row) for row in rows]}


@router.get("/interview-sessions/{session_id}/coding-tasks/{task_id}/code")
async def get_code_staff(
    session_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    task = await _staff_task(db, session, task_id)
    snapshot = await _latest_snapshot(db, task.id)
    return {"source": snapshot.source if snapshot else task.starter_code}


@router.get("/interview-sessions/{session_id}/coding-tasks/{task_id}/executions")
async def list_executions_staff(
    session_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    task = await _staff_task(db, session, task_id)
    rows = (
        (
            await db.execute(
                select(CodeExecution)
                .where(CodeExecution.task_id == task.id)
                .order_by(CodeExecution.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"executions": [_execution_view(row) for row in rows]}


@router.get("/interview-sessions/{session_id}/whiteboard")
async def list_whiteboard_staff(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    rows = (
        (
            await db.execute(
                select(WhiteboardStroke)
                .where(WhiteboardStroke.session_id == session.id)
                .order_by(WhiteboardStroke.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"strokes": [_stroke_view(row) for row in rows]}


@router.post("/interview-sessions/{session_id}/whiteboard", status_code=201)
async def add_stroke_staff(
    session_id: uuid.UUID,
    body: StrokeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    if len(str(body.stroke_payload)) > MAX_STROKE_PAYLOAD_LEN:
        raise HTTPException(status_code=400, detail="stroke_payload too large")
    stroke = WhiteboardStroke(
        organization_id=session.organization_id,
        session_id=session.id,
        author="interviewer",
        stroke_payload=body.stroke_payload,
    )
    db.add(stroke)
    await db.flush()
    return _stroke_view(stroke)


@router.get("/interview-sessions/{session_id}/discussion")
async def list_discussion_staff(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    rows = (
        (
            await db.execute(
                select(DiscussionMessage)
                .where(DiscussionMessage.session_id == session.id)
                .order_by(DiscussionMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"messages": [_message_view(row) for row in rows]}


@router.post("/interview-sessions/{session_id}/discussion", status_code=201)
async def post_discussion_staff(
    session_id: uuid.UUID,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    session = await _staff_session(db, user, session_id)
    message = DiscussionMessage(
        organization_id=session.organization_id,
        session_id=session.id,
        task_id=None,
        author="interviewer",
        author_label=user.email,
        body=body.body,
    )
    db.add(message)
    await db.flush()
    return _message_view(message)


# ---------------------------------------------------------------------------
# Public (token-gated candidate) endpoints
# ---------------------------------------------------------------------------


async def _public_task(
    db: AsyncSession, session: InterviewSession, task_id: uuid.UUID
) -> CodingTask:
    task = (
        await db.execute(select(CodingTask).where(CodingTask.id == task_id))
    ).scalar_one_or_none()
    if task is None or task.session_id != session.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _require_active(session: InterviewSession) -> None:
    if session.status != InterviewSessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")


def _require_not_terminal(session: InterviewSession) -> None:
    if _terminal(session.status):
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")


@router.get("/public/interview-sessions/{raw_token}/coding-tasks")
async def list_tasks_public(
    raw_token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_not_terminal(session)
    rows = (
        (
            await db.execute(
                select(CodingTask)
                .where(CodingTask.session_id == session.id)
                .order_by(CodingTask.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"tasks": [_task_view(row) for row in rows]}


@router.get("/public/interview-sessions/{raw_token}/coding-tasks/{task_id}/code")
async def get_code_public(
    raw_token: str, task_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_not_terminal(session)
    task = await _public_task(db, session, task_id)
    snapshot = await _latest_snapshot(db, task.id)
    return {"source": snapshot.source if snapshot else task.starter_code}


@router.post("/public/interview-sessions/{raw_token}/coding-tasks/{task_id}/code", status_code=201)
async def save_code_public(
    raw_token: str, task_id: uuid.UUID, body: CodeSave, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_active(session)
    task = await _public_task(db, session, task_id)
    snapshot = CodeSnapshot(
        organization_id=session.organization_id, task_id=task.id, source=body.source
    )
    db.add(snapshot)
    await db.flush()
    return {"saved_at": snapshot.created_at.isoformat()}


@router.post("/public/interview-sessions/{raw_token}/coding-tasks/{task_id}/run")
async def run_code_public(
    raw_token: str,
    task_id: uuid.UUID,
    body: RunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    settings: Settings = get_app_settings(request)
    session = await _session_by_token(db, raw_token)
    _require_active(session)
    task = await _public_task(db, session, task_id)

    db.add(
        CodeSnapshot(organization_id=session.organization_id, task_id=task.id, source=body.source)
    )
    result = await _execute_via_sandbox(settings, task.language, body.source, body.stdin)

    execution = CodeExecution(
        organization_id=session.organization_id,
        task_id=task.id,
        source=body.source,
        stdin=body.stdin,
        stdout=str(result.get("stdout", "")),
        stderr=str(result.get("stderr", "")),
        exit_code=result.get("exit_code"),
        timed_out=bool(result.get("timed_out", False)),
        truncated=bool(result.get("truncated", False)),
        duration_ms=int(result.get("duration_ms", 0)),
    )
    db.add(execution)
    await record_event(
        db,
        action="workspace.code_executed",
        entity_type="coding_task",
        entity_id=task.id,
        organization_id=session.organization_id,
        payload={
            "exit_code": execution.exit_code,
            "timed_out": execution.timed_out,
            "duration_ms": execution.duration_ms,
        },
    )
    await db.flush()
    return _execution_view(execution)


@router.get("/public/interview-sessions/{raw_token}/whiteboard")
async def list_whiteboard_public(
    raw_token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_not_terminal(session)
    rows = (
        (
            await db.execute(
                select(WhiteboardStroke)
                .where(WhiteboardStroke.session_id == session.id)
                .order_by(WhiteboardStroke.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"strokes": [_stroke_view(row) for row in rows]}


@router.post("/public/interview-sessions/{raw_token}/whiteboard", status_code=201)
async def add_stroke_public(
    raw_token: str, body: StrokeCreate, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_active(session)
    if len(str(body.stroke_payload)) > MAX_STROKE_PAYLOAD_LEN:
        raise HTTPException(status_code=400, detail="stroke_payload too large")
    stroke = WhiteboardStroke(
        organization_id=session.organization_id,
        session_id=session.id,
        author="candidate",
        stroke_payload=body.stroke_payload,
    )
    db.add(stroke)
    await db.flush()
    return _stroke_view(stroke)


@router.get("/public/interview-sessions/{raw_token}/discussion")
async def list_discussion_public(
    raw_token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_not_terminal(session)
    rows = (
        (
            await db.execute(
                select(DiscussionMessage)
                .where(DiscussionMessage.session_id == session.id)
                .order_by(DiscussionMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"messages": [_message_view(row) for row in rows]}


@router.post("/public/interview-sessions/{raw_token}/discussion", status_code=201)
async def post_discussion_public(
    raw_token: str, body: MessageCreate, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_active(session)
    message = DiscussionMessage(
        organization_id=session.organization_id,
        session_id=session.id,
        task_id=None,
        author="candidate",
        author_label=session.candidate_email,
        body=body.body,
    )
    db.add(message)
    await db.flush()
    return _message_view(message)


@router.post("/public/interview-sessions/{raw_token}/screen-share/token")
async def screen_share_token(
    raw_token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    session = await _session_by_token(db, raw_token)
    _require_not_terminal(session)
    raise HTTPException(
        status_code=501,
        detail=(
            "Screen share requires WebRTC/LiveKit infrastructure not present in this "
            "deployment (same deferral class as M8's GPU-backed STT/TTS backends); "
            "the interface is stable but no backend is wired up yet"
        ),
    )


__all__ = ["router"]
