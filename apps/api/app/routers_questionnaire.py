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
from app.deps import get_app_settings, get_db, get_email_provider, require_roles
from app.email import EmailProvider
from app.models import (
    Department,
    ExtractedFieldRow,
    JobDescription,
    Questionnaire,
    QuestionnaireInvite,
    QuestionnaireResponse,
    Requisition,
    ResumeDocument,
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
from app.rate_limit import PUBLIC_ENDPOINT_LIMIT, limiter
from app.settings import Settings
from app.validation import EmailAddress

router = APIRouter(tags=["questionnaires"])


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


@router.get("/requisitions/{requisition_id}/questionnaires")
async def list_questionnaires(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    rows = (
        (
            await db.execute(
                select(Questionnaire)
                .where(Questionnaire.requisition_id == requisition_id)
                .order_by(Questionnaire.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "questionnaires": [
            {"id": str(row.id), "title": row.title, "question_count": len(row.questions)}
            for row in rows
        ]
    }


class QuestionnaireClone(BaseModel):
    target_requisition_id: uuid.UUID


@router.post("/questionnaires/{questionnaire_id}/clone", status_code=201)
async def clone_questionnaire(
    questionnaire_id: uuid.UUID,
    body: QuestionnaireClone,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    """M11 'interview kits': reuse a proven questionnaire on a new
    requisition instead of rebuilding it by hand. Scoped to questionnaires
    only — coding tasks are session-scoped in this schema (M9), not
    requisition-scoped, so a reusable coding-task library would need a new
    template entity; left for a future pass rather than half-built here."""
    source = (
        await db.execute(select(Questionnaire).where(Questionnaire.id == questionnaire_id))
    ).scalar_one_or_none()
    if source is None or source.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    await _load_requisition(db, user, body.target_requisition_id)

    clone = Questionnaire(
        organization_id=user.organization_id,
        requisition_id=body.target_requisition_id,
        title=source.title,
        questions=source.questions,
    )
    db.add(clone)
    await db.flush()
    await record_event(
        db,
        action="questionnaire.cloned",
        entity_type="questionnaire",
        entity_id=clone.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"source_questionnaire_id": str(source.id)},
    )
    return {
        "id": str(clone.id),
        "title": clone.title,
        "question_count": len(clone.questions),
        "requisition_id": str(body.target_requisition_id),
    }


@router.post("/questionnaires/{questionnaire_id}/invites", status_code=201)
async def create_invite(
    questionnaire_id: uuid.UUID,
    body: InviteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
    email: EmailProvider = Depends(get_email_provider),
) -> dict[str, object]:
    from app.settings import get_settings

    questionnaire = (
        await db.execute(select(Questionnaire).where(Questionnaire.id == questionnaire_id))
    ).scalar_one_or_none()
    if questionnaire is None or questionnaire.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    settings = get_settings()
    days = settings.invite_token_days

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
    portal_link = f"{settings.candidate_portal_url}/questionnaire/{raw}"
    await email.send(
        to=invite.candidate_email,
        subject=f"{questionnaire.title} — action needed",
        body=(
            f"You've been invited to complete a short questionnaire: {questionnaire.title}.\n\n"
            f"{portal_link}\n\n"
            f"This link expires in {days} days and can only be used once."
        ),
    )
    return {
        "invite_id": str(invite.id),
        "token": raw,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.get("/public/questionnaires/{raw_token}")
@limiter.limit(PUBLIC_ENDPOINT_LIMIT)
async def get_public_questionnaire(
    request: Request, raw_token: str, db: AsyncSession = Depends(get_db)
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
@limiter.limit(PUBLIC_ENDPOINT_LIMIT)
async def upsert_response(
    raw_token: str,
    body: ResponseUpsert,
    request: Request,
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
        await db.execute(
            select(QuestionnaireResponse, QuestionnaireInvite.candidate_email)
            .join(QuestionnaireInvite, QuestionnaireInvite.id == QuestionnaireResponse.invite_id)
            .join(Questionnaire, Questionnaire.id == QuestionnaireInvite.questionnaire_id)
            .where(Questionnaire.requisition_id == requisition_id)
            .order_by(QuestionnaireResponse.updated_at.desc())
        )
    ).all()
    return {
        "responses": [
            {
                "id": str(row.id),
                "candidate_email": candidate_email,
                "submitted": row.submitted,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "missing_required": row.missing_required,
                "history_entries": len(row.history),
                "answers": row.answers,
                "ai_evaluation": row.ai_evaluation,
            }
            for row, candidate_email in rows
        ]
    }


async def _gateway_questionnaire_evaluation(
    settings: Settings,
    jd_clause: str,
    qa_pairs: str,
    resume_spans: str,
    seed_key: str,
) -> dict[str, object]:
    if not settings.ai_gateway_url:
        raise HTTPException(status_code=503, detail="AI gateway not configured")
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/generate",
                json={
                    "prompt_id": "questionnaire_evaluation",
                    "response_model": "QuestionnaireEvaluation",
                    "inputs": {
                        "jd_clause": jd_clause,
                        "qa_pairs": qa_pairs,
                        "resume_spans": resume_spans,
                    },
                    "seed_key": seed_key,
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI gateway call failed: {exc}") from exc
    return dict(response.json()["data"])


@router.post("/questionnaire-responses/{response_id}/evaluate")
async def evaluate_response(
    response_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    """AI evaluation of a submitted questionnaire: overall score, a
    recommendation, inconsistencies against the candidate's resume (best-
    effort matched by email within the same organization -- there is no
    direct resume_id link on a questionnaire response), and missing
    critical information. Explicitly scoped out of Milestone 6 pending a
    real AI model; unblocked by ADR-024, delivered here (ADR-033)."""
    row = (
        await db.execute(
            select(QuestionnaireResponse, QuestionnaireInvite, Questionnaire)
            .join(QuestionnaireInvite, QuestionnaireInvite.id == QuestionnaireResponse.invite_id)
            .join(Questionnaire, Questionnaire.id == QuestionnaireInvite.questionnaire_id)
            .where(QuestionnaireResponse.id == response_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Response not found")
    response_row, invite, questionnaire = row
    if response_row.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Response not found")
    if not response_row.submitted:
        raise HTTPException(status_code=409, detail="Response has not been submitted yet")

    questions_by_id = {q["id"]: q for q in questionnaire.questions}
    qa_lines = []
    for question_id, answer in response_row.answers.items():
        prompt_text = questions_by_id.get(question_id, {}).get("prompt", question_id)
        qa_lines.append(f"{question_id}: {prompt_text} -> {answer}")
    qa_pairs = "\n".join(qa_lines) or "(no answers recorded)"

    jd = (
        await db.execute(
            select(JobDescription)
            .where(JobDescription.requisition_id == questionnaire.requisition_id)
            .order_by(JobDescription.version.desc(), JobDescription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    jd_clause = jd.raw_text[:500] if jd else ""

    # Best-effort resume match: no direct FK from a questionnaire response
    # to a resume, so match by candidate email within the same org, same
    # pattern DSAR/retention already use for the same reason.
    resume = (
        (
            await db.execute(
                select(ResumeDocument).where(
                    ResumeDocument.organization_id == user.organization_id,
                    ResumeDocument.candidate_email == invite.candidate_email,
                )
            )
        )
        .scalars()
        .first()
    )
    resume_spans = ""
    if resume is not None:
        fields = (
            (
                await db.execute(
                    select(ExtractedFieldRow).where(ExtractedFieldRow.resume_id == resume.id)
                )
            )
            .scalars()
            .all()
        )
        resume_spans = "\n".join(f"{f.field_name}: {f.source_quote}" for f in fields[:12])

    settings = get_app_settings(request)
    evaluation = await _gateway_questionnaire_evaluation(
        settings,
        jd_clause,
        qa_pairs,
        resume_spans,
        seed_key=f"{response_id}:{response_row.updated_at.isoformat()}",
    )

    response_row.ai_evaluation = evaluation
    await record_event(
        db,
        action="questionnaire_response.evaluated",
        entity_type="questionnaire_response",
        entity_id=response_row.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"recommendation": evaluation.get("recommendation")},
    )
    await db.flush()
    return evaluation
