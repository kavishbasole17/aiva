"""M10 evaluation engine: aggregates resume/questionnaire/interview/coding
signals into one persisted, exportable evaluation report.

Aggregation and verdict assignment are entirely deterministic
(`evaluation_engine.py`) — the gateway-backed narrative only ever explains
an already-computed verdict, it never produces a different one, same
"LLM never performs arithmetic" discipline `scoring.py` established for
resume dimension judgements.
"""

import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_app_settings, get_db, require_roles
from app.evaluation_engine import ComponentScore, compute_overall
from app.models import (
    CodeExecution,
    CodingTask,
    EvaluationReport,
    InterviewSession,
    InterviewSessionStatus,
    InterviewTurn,
    Questionnaire,
    QuestionnaireInvite,
    QuestionnaireResponse,
    Requisition,
    ResumeDocument,
    Role,
    ScoringRunRow,
    User,
)
from app.report_export import render_pdf, render_xlsx
from app.routers_resume import _load_requisition
from app.settings import Settings

router = APIRouter(tags=["evaluation"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)


async def _resume_component(db: AsyncSession, resume_id: uuid.UUID) -> ComponentScore | None:
    run = (
        await db.execute(
            select(ScoringRunRow)
            .where(ScoringRunRow.resume_id == resume_id)
            .order_by(ScoringRunRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    return ComponentScore("resume", run.total_score, f"resume verdict: {run.verdict}")


async def _questionnaire_component(
    db: AsyncSession, requisition_id: uuid.UUID, candidate_email: str | None
) -> ComponentScore | None:
    if not candidate_email:
        return None
    invite = (
        await db.execute(
            select(QuestionnaireInvite)
            .join(Questionnaire, Questionnaire.id == QuestionnaireInvite.questionnaire_id)
            .where(
                Questionnaire.requisition_id == requisition_id,
                QuestionnaireInvite.candidate_email == candidate_email,
            )
            .order_by(QuestionnaireInvite.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if invite is None:
        return None
    response = (
        await db.execute(
            select(QuestionnaireResponse).where(QuestionnaireResponse.invite_id == invite.id)
        )
    ).scalar_one_or_none()
    if response is None:
        return ComponentScore("questionnaire", 0, "invited, not yet started")
    if response.submitted:
        return ComponentScore("questionnaire", 100, "submitted, all required questions answered")
    questionnaire = (
        await db.execute(select(Questionnaire).where(Questionnaire.id == invite.questionnaire_id))
    ).scalar_one()
    total_questions = max(1, len(questionnaire.questions))
    ratio = min(1.0, len(response.answers) / total_questions)
    return ComponentScore(
        "questionnaire",
        round(100 * ratio),
        f"{len(response.answers)}/{total_questions} answered, not yet submitted",
    )


async def _interview_component(
    db: AsyncSession, resume_id: uuid.UUID
) -> tuple[ComponentScore | None, InterviewSession | None]:
    session = (
        await db.execute(
            select(InterviewSession)
            .where(InterviewSession.resume_id == resume_id)
            .order_by(InterviewSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if session is None:
        return None, None
    turns = (
        (await db.execute(select(InterviewTurn).where(InterviewTurn.session_id == session.id)))
        .scalars()
        .all()
    )
    answered = sum(1 for turn in turns if turn.answer_text is not None)
    total = max(1, len(session.asked_turns) or len(turns))
    if session.status == InterviewSessionStatus.COMPLETED.value:
        score = 100
    else:
        score = round(100 * min(1.0, answered / total))
    detail = f"{answered} answered turns, session status={session.status}"
    return ComponentScore("interview", score, detail), session


async def _coding_component(db: AsyncSession, session_id: uuid.UUID) -> ComponentScore | None:
    tasks = (
        (await db.execute(select(CodingTask).where(CodingTask.session_id == session_id)))
        .scalars()
        .all()
    )
    if not tasks:
        return None
    passed = 0
    for task in tasks:
        latest = (
            await db.execute(
                select(CodeExecution)
                .where(CodeExecution.task_id == task.id)
                .order_by(CodeExecution.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None and latest.exit_code == 0 and not latest.timed_out:
            passed += 1
    return ComponentScore(
        "coding", round(100 * passed / len(tasks)), f"{passed}/{len(tasks)} tasks passed"
    )


async def _generate_narrative(
    settings: Settings, resume_id: uuid.UUID, components: list[ComponentScore]
) -> dict[str, Any] | None:
    if not settings.ai_gateway_url:
        return None
    by_name = {component.name: component for component in components}

    def detail(name: str) -> str:
        found = by_name.get(name)
        return found.detail if found else "no data available"

    inputs = {
        "resume_summary": detail("resume"),
        "questionnaire_summary": detail("questionnaire"),
        "interview_summary": detail("interview"),
        "coding_summary": detail("coding"),
    }
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/generate",
                json={
                    "prompt_id": "evaluation_summary",
                    "response_model": "EvaluationSummary",
                    "inputs": inputs,
                    "seed_key": resume_id.hex,
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            return dict(payload["data"])
    except httpx.HTTPError:
        return None  # narrative is a nice-to-have; the deterministic verdict still stands


@router.post("/requisitions/{requisition_id}/resumes/{resume_id}/evaluation", status_code=201)
async def generate_evaluation(
    requisition_id: uuid.UUID,
    resume_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    settings = get_app_settings(request)
    requisition: Requisition = await _load_requisition(db, user, requisition_id)
    resume = (
        await db.execute(select(ResumeDocument).where(ResumeDocument.id == resume_id))
    ).scalar_one_or_none()
    if (
        resume is None
        or resume.organization_id != user.organization_id
        or resume.requisition_id != requisition_id
    ):
        raise HTTPException(status_code=404, detail="Resume not found")

    components: list[ComponentScore] = []
    resume_component = await _resume_component(db, resume_id)
    if resume_component is not None:
        components.append(resume_component)
    questionnaire_component = await _questionnaire_component(
        db, requisition_id, resume.candidate_email
    )
    if questionnaire_component is not None:
        components.append(questionnaire_component)
    interview_component, session = await _interview_component(db, resume_id)
    if interview_component is not None:
        components.append(interview_component)
    coding_component = await _coding_component(db, session.id) if session is not None else None
    if coding_component is not None:
        components.append(coding_component)

    if not components:
        raise HTTPException(
            status_code=409,
            detail="No signal yet to evaluate this candidate (no resume score, "
            "questionnaire response, or interview session found)",
        )

    overall, verdict = compute_overall(components)
    narrative_data = await _generate_narrative(settings, resume_id, components)

    payload: dict[str, object] = {
        "candidate_email": resume.candidate_email or "unknown",
        "requisition_title": requisition.title,
        "overall_score": overall,
        "verdict": verdict,
        "components": [{"name": c.name, "score": c.score, "detail": c.detail} for c in components],
        "narrative": narrative_data["narrative"] if narrative_data else None,
        "strengths": narrative_data["strengths"] if narrative_data else [],
        "concerns": narrative_data["concerns"] if narrative_data else [],
    }
    report = EvaluationReport(
        organization_id=user.organization_id,
        requisition_id=requisition_id,
        resume_id=resume_id,
        verdict=verdict,
        overall_score=overall,
        payload=payload,
        generated_by=user.id,
    )
    db.add(report)
    await db.flush()
    return {"id": str(report.id), "created_at": report.created_at.isoformat(), **payload}


@router.get("/requisitions/{requisition_id}/resumes/{resume_id}/evaluation")
async def get_latest_evaluation(
    requisition_id: uuid.UUID,
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    report = (
        await db.execute(
            select(EvaluationReport)
            .where(
                EvaluationReport.requisition_id == requisition_id,
                EvaluationReport.resume_id == resume_id,
            )
            .order_by(EvaluationReport.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="No evaluation generated yet")
    return {"id": str(report.id), "created_at": report.created_at.isoformat(), **report.payload}


async def _load_report(db: AsyncSession, user: User, report_id: uuid.UUID) -> EvaluationReport:
    report = (
        await db.execute(select(EvaluationReport).where(EvaluationReport.id == report_id))
    ).scalar_one_or_none()
    if report is None or report.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/evaluation-reports/{report_id}/export.pdf")
async def export_pdf(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> Response:
    report = await _load_report(db, user, report_id)
    return Response(
        content=render_pdf(report.payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="evaluation-{report.id}.pdf"'},
    )


@router.get("/evaluation-reports/{report_id}/export.xlsx")
async def export_xlsx(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> Response:
    report = await _load_report(db, user, report_id)
    return Response(
        content=render_xlsx(report.payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="evaluation-{report.id}.xlsx"'},
    )


__all__ = ["router"]
