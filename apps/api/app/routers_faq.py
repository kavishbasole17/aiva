"""M10 RAG FAQ: staff-authored, requisition-scoped documents answered against
via retrieval-augmented generation for the candidate.

Same two-sided shape as the workspace/interview routers: staff (JWT) write
FAQ documents; the candidate (raw token, same discipline as every other
public endpoint) asks a question and gets a grounded answer. Retrieval is
real pgvector cosine-similarity search — the LLM only ever sees the
documents retrieval actually found, it never invents the retrieval step.
"""

import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_app_settings, get_db, require_roles
from app.models import FaqDocument, Role, User
from app.rate_limit import PUBLIC_ENDPOINT_LIMIT, limiter
from app.routers_interview import _session_by_token, _terminal
from app.routers_resume import _load_requisition
from app.settings import Settings

router = APIRouter(tags=["faq"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)

RETRIEVAL_TOP_K = 3


class FaqCreate(BaseModel):
    title: str = PydField(min_length=1, max_length=200)
    body: str = PydField(min_length=1, max_length=8000)


class FaqAsk(BaseModel):
    question: str = PydField(min_length=1, max_length=2000)


def _faq_view(row: FaqDocument) -> dict[str, object]:
    return {
        "id": str(row.id),
        "title": row.title,
        "body": row.body,
        "created_at": row.created_at.isoformat(),
    }


async def _embed(settings: Settings, text: str) -> list[float]:
    if not settings.ai_gateway_url:
        raise HTTPException(status_code=503, detail="AI gateway URL is not configured")
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post("/v1/embed", json={"text": text})
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"AI gateway unreachable: {exc}") from exc
    return [float(component) for component in payload["vector"]]


async def _generate(
    settings: Settings, prompt_id: str, response_model: str, inputs: dict[str, str], seed_key: str
) -> dict[str, Any]:
    if not settings.ai_gateway_url:
        raise HTTPException(status_code=503, detail="AI gateway URL is not configured")
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/generate",
                json={
                    "prompt_id": prompt_id,
                    "response_model": response_model,
                    "inputs": inputs,
                    "seed_key": seed_key,
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"AI gateway unreachable: {exc}") from exc
    return payload


@router.post("/requisitions/{requisition_id}/faq", status_code=201)
async def create_faq(
    requisition_id: uuid.UUID,
    body: FaqCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    settings = get_app_settings(request)
    await _load_requisition(db, user, requisition_id)
    vector = await _embed(settings, f"{body.title}\n{body.body}")
    row = FaqDocument(
        organization_id=user.organization_id,
        requisition_id=requisition_id,
        title=body.title,
        body=body.body,
        embedding=vector,
        embedding_model_id="ai-gateway",
        created_by=user.id,
    )
    db.add(row)
    await db.flush()
    return _faq_view(row)


@router.get("/requisitions/{requisition_id}/faq")
async def list_faq(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    rows = (
        (
            await db.execute(
                select(FaqDocument)
                .where(FaqDocument.requisition_id == requisition_id)
                .order_by(FaqDocument.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"documents": [_faq_view(row) for row in rows]}


@router.post("/public/interview-sessions/{raw_token}/faq")
@limiter.limit(PUBLIC_ENDPOINT_LIMIT)
async def ask_faq(
    raw_token: str,
    body: FaqAsk,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    settings = get_app_settings(request)
    session = await _session_by_token(db, raw_token)
    if _terminal(session.status):
        raise HTTPException(status_code=409, detail=f"Unexpected state: {session.status}")

    query_vector = await _embed(settings, body.question)
    retrieved = (
        (
            await db.execute(
                select(FaqDocument)
                .where(FaqDocument.requisition_id == session.requisition_id)
                .order_by(FaqDocument.embedding.cosine_distance(query_vector))
                .limit(RETRIEVAL_TOP_K)
            )
        )
        .scalars()
        .all()
    )
    if not retrieved:
        return {
            "answer": (
                "No FAQ documents are available for this role yet — " "ask your recruiter directly."
            ),
            "confidence": 0.0,
            "cited_document_ids": [],
            "retrieved": [],
        }

    documents_block = "\n".join(f"{row.id}: {row.title} — {row.body}" for row in retrieved)
    result = await _generate(
        settings,
        prompt_id="faq_answer",
        response_model="FaqAnswer",
        inputs={"question": body.question, "retrieved_documents": documents_block},
        seed_key=str(session.id),
    )
    data = result["data"]
    return {
        "answer": data["answer"],
        "confidence": data["confidence"],
        "cited_document_ids": data["cited_span_ids"],
        "retrieved": [{"id": str(row.id), "title": row.title} for row in retrieved],
    }


__all__ = ["router"]
