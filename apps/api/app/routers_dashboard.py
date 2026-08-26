"""M11 recruiter dashboard: org-wide pipeline aggregates.

Every number here is a straight SQL aggregate (COUNT/GROUP BY) scoped by
the same RLS the rest of the app relies on — no candidate-identifying data
crosses this endpoint, only counts. Nothing here is a judgement; it's a
summary of judgements and events that already happened elsewhere.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_roles
from app.models import (
    CodeExecution,
    CodingTask,
    Department,
    InterviewSession,
    QuestionnaireResponse,
    Requisition,
    RequisitionStatus,
    ResumeDocument,
    Role,
    ScoringRunRow,
    User,
)
from app.routers_org import _get_org

router = APIRouter(tags=["dashboard"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
    Role.INTERVIEWER.value,
    Role.AUDITOR.value,
)


async def _counts_by(db: AsyncSession, column: Any, *filters: Any) -> dict[str, int]:
    rows = (await db.execute(select(column, func.count()).where(*filters).group_by(column))).all()
    return {str(key): count for key, count in rows}


@router.get("/orgs/{organization_id}/dashboard")
async def get_dashboard(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _get_org(db, organization_id)

    requisition_total = (
        await db.execute(
            select(func.count(Requisition.id))
            .join(Department, Department.id == Requisition.department_id)
            .where(Department.organization_id == organization_id)
        )
    ).scalar_one()
    requisitions_by_status = {
        str(status): count
        for status, count in (
            await db.execute(
                select(Requisition.status, func.count())
                .join(Department, Department.id == Requisition.department_id)
                .where(Department.organization_id == organization_id)
                .group_by(Requisition.status)
            )
        ).all()
    }

    resume_total = (
        await db.execute(
            select(func.count(ResumeDocument.id)).where(
                ResumeDocument.organization_id == organization_id
            )
        )
    ).scalar_one()

    verdict_counts = await _counts_by(
        db, ScoringRunRow.verdict, ScoringRunRow.organization_id == organization_id
    )

    interview_status_counts = await _counts_by(
        db, InterviewSession.status, InterviewSession.organization_id == organization_id
    )

    questionnaire_total = (
        await db.execute(
            select(func.count(QuestionnaireResponse.id)).where(
                QuestionnaireResponse.organization_id == organization_id
            )
        )
    ).scalar_one()
    questionnaire_submitted = (
        await db.execute(
            select(func.count(QuestionnaireResponse.id)).where(
                QuestionnaireResponse.organization_id == organization_id,
                QuestionnaireResponse.submitted.is_(True),
            )
        )
    ).scalar_one()

    coding_task_total = (
        await db.execute(
            select(func.count(CodingTask.id)).where(CodingTask.organization_id == organization_id)
        )
    ).scalar_one()
    # "Passed" means the task's most recent execution succeeded — mirrors
    # evaluation_engine.py's per-task pass definition, aggregated org-wide
    # instead of per-candidate. Joins on (task_id, created_at) rather than
    # max(id): Postgres has no max() aggregate for uuid, and created_at is
    # what "most recent" actually means here anyway.
    latest_per_task = (
        select(
            CodeExecution.task_id.label("task_id"),
            func.max(CodeExecution.created_at).label("latest_at"),
        )
        .where(CodeExecution.organization_id == organization_id)
        .group_by(CodeExecution.task_id)
        .subquery()
    )
    coding_task_passed = (
        await db.execute(
            select(func.count(CodeExecution.id))
            .join(
                latest_per_task,
                (CodeExecution.task_id == latest_per_task.c.task_id)
                & (CodeExecution.created_at == latest_per_task.c.latest_at),
            )
            .where(
                CodeExecution.organization_id == organization_id,
                CodeExecution.exit_code == 0,
                CodeExecution.timed_out.is_(False),
            )
        )
    ).scalar_one()

    return {
        "requisitions": {
            "total": requisition_total,
            "by_status": requisitions_by_status,
            "open": requisitions_by_status.get(RequisitionStatus.OPEN.value, 0),
        },
        "resumes": {"total": resume_total},
        "scoring": {"by_verdict": verdict_counts},
        "interviews": {"by_status": interview_status_counts},
        "questionnaires": {
            "total": questionnaire_total,
            "submitted": questionnaire_submitted,
            "submission_rate": (
                round(questionnaire_submitted / questionnaire_total, 3)
                if questionnaire_total
                else None
            ),
        },
        "coding_tasks": {
            "total": coding_task_total,
            "passed_latest_run": coding_task_passed,
            "pass_rate": (
                round(coding_task_passed / coding_task_total, 3) if coding_task_total else None
            ),
        },
    }


__all__ = ["router"]
