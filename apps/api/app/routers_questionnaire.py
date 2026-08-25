import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_db, require_roles
from app.models import (
    Department,
    Questionnaire,
    QuestionnaireInvite,
    QuestionnaireResponse,
    Requisition,
    Role,
    User,
    utcnow,
)
from app.questionnaire_service import (
    generate_invite_token,
    hash_token,
    missing_required_answers,
    validate_questions,
)
from app.validation import EmailAddress

router = APIRouter(tags=["questionnaires"])


def get_app_settings_days() -> int:
    from app.settings import get_settings

    return get_settings().invite_token_days


EDIT_ROLES = (Role.ADMIN.value, Role.HIRING_MANAGER.value, Role.RECRUITER.value)
STAFF_ROLES = (*EDIT_ROLES, Role.INTERVIEWER.value, Role.AUDITOR.value)


class QuestionnaireCreate(BaseModel):
    title: str = PydField(min_length=1, max_length=200)
    questions: list[dict[str, Any]] = PydField(min_length=1)


class InviteCreate(BaseModel):
    candidate_email: EmailAddress


class ResponseUpsert(BaseModel):
    answers: dict[str, Any]
    submit: bool = False


async def _load_requisition(db: AsyncSession, user: User, rid: uuid.UUID) -> None:
    req = (await db.execute(select(Requisition).where(Requisition.id == rid))).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    dept = (
        await db.execute(select(Department).where(Department.id == req.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Requisition not found")


@router.post("/requisitions/{requisition_id}/questionnaires", status_code=201)
async def create_questionnaire(
    requisition_id: uuid.UUID,
    body: QuestionnaireCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    errors = validate_questions(body.questions)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    questionnaire = Questionnaire(
        organization_id=user.organization_id,
        requisition_id=requisition_id,
        title=body.title,
        questions=body.questions,
    )
    db.add(questionnaire)
    await db.flush()
    await record_event(
        db,
        action="questionnaire.created",
        entity_type="questionnaire",
        entity_id=questionnaire.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"title": body.title, "question_count": len(body.questions)},
    )
    return {"id": str(questionnaire.id), "question_count": len(body.questions)}


@router.post("/questionnaires/{questionnaire_id}/invites", status_code=201)
async def create_invite(
    questionnaire_id: uuid.UUID,
    body: InviteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    questionnaire = (
        await db.execute(select(Questionnaire).where(Questionnaire.id == questionnaire_id))
    ).scalar_one_or_none()
    if questionnaire is None or questionnaire.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    days = get_app_settings_days()

    raw, digest = generate_invite_token()
    invite = QuestionnaireInvite(
        organization_id=user.organization_id,
        questionnaire_id=questionnaire_id,
        candidate_email=body.candidate_email.lower(),
        token_hash=digest,
        expires_at=utcnow() + timedelta(days=days),
    )
    db.add(invite)
    await db.flush()
    await record_event(
        db,
        action="questionnaire.invited",
        entity_type="questionnaire_invite",
        entity_id=invite.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"candidate_email": invite.candidate_email},
    )
    return {
        "invite_id": str(invite.id),
        "token": raw,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.get("/public/questionnaires/{raw_token}")
async def get_public_questionnaire(
    raw_token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    invite = (
        await db.execute(
            select(QuestionnaireInvite).where(
                QuestionnaireInvite.token_hash == hash_token(raw_token)
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.completed_at is not None:
        raise HTTPException(status_code=409, detail="Already completed")
    if invite.expires_at < utcnow():
        raise HTTPException(status_code=410, detail="Invitation expired")

    questionnaire = (
        await db.execute(select(Questionnaire).where(Questionnaire.id == invite.questionnaire_id))
    ).scalar_one()
    response_row = (
        await db.execute(
            select(QuestionnaireResponse).where(QuestionnaireResponse.invite_id == invite.id)
        )
    ).scalar_one_or_none()
    return {
        "title": questionnaire.title,
        "questions": questionnaire.questions,
        "answers": (response_row.answers if response_row else {}),
        "candidate_email": invite.candidate_email,
    }


@router.put("/public/questionnaires/{raw_token}/responses")
async def upsert_response(
    raw_token: str,
    body: ResponseUpsert,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    invite = (
        await db.execute(
            select(QuestionnaireInvite).where(
                QuestionnaireInvite.token_hash == hash_token(raw_token)
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.completed_at is not None:
        raise HTTPException(status_code=409, detail="Already completed")
    if invite.expires_at < utcnow():
        raise HTTPException(status_code=410, detail="Invitation expired")

    questionnaire = (
        await db.execute(select(Questionnaire).where(Questionnaire.id == invite.questionnaire_id))
    ).scalar_one()

    row = (
        await db.execute(
            select(QuestionnaireResponse).where(QuestionnaireResponse.invite_id == invite.id)
        )
    ).scalar_one_or_none()

    now = utcnow()
    if row is None:
        row = QuestionnaireResponse(
            organization_id=invite.organization_id,
            invite_id=invite.id,
            answers={},
            history=[],
        )
        db.add(row)

    row.history.append({"at": now.isoformat(), "answers": body.answers})
    row.answers = body.answers
    row.missing_required = missing_required_answers(questionnaire.questions, body.answers)

    if body.submit:
        if row.missing_required:
            raise HTTPException(
                status_code=400,
                detail={"missing_required": row.missing_required},
            )
        row.submitted = True
        row.submitted_at = now
        invite.completed_at = now
        await record_event(
            db,
            action="questionnaire.submitted",
            entity_type="questionnaire_response",
            entity_id=row.id,
            organization_id=invite.organization_id,
        )

    await db.flush()
    return {
        "saved": True,
        "submitted": row.submitted,
        "missing_required": row.missing_required,
        "history_entries": len(row.history),
    }


@router.get("/requisitions/{requisition_id}/questionnaire-responses")
async def list_responses(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    rows = (
        (
            await db.execute(
                select(QuestionnaireResponse)
                .join(
                    QuestionnaireInvite, QuestionnaireInvite.id == QuestionnaireResponse.invite_id
                )
                .join(Questionnaire, Questionnaire.id == QuestionnaireInvite.questionnaire_id)
                .where(Questionnaire.requisition_id == requisition_id)
                .order_by(QuestionnaireResponse.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "responses": [
            {
                "id": str(row.id),
                "submitted": row.submitted,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "missing_required": row.missing_required,
                "history_entries": len(row.history),
            }
            for row in rows
        ]
    }
