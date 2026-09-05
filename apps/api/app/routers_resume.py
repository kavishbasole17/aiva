import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_app_settings, get_db, require_roles
from app.matching import JobRequirements, match_ratio, run_match_checks, to_payload
from app.models import (
    Department,
    ExtractedFieldRow,
    JobDescription,
    Requisition,
    ResumeDocument,
    Role,
    ScoringRunRow,
    User,
    WeightProfileRow,
)
from app.scoring import (
    DIMENSION_NAMES,
    DimensionInput,
    WeightProfile,
    assign_verdict,
    compute_total_score,
    run_fingerprint,
    technical_dimension_from_checks,
    validate_profile,
)
from app.scoring_audit import ScoringRunFacts, run_audit
from app.settings import Settings
from app.text_extract import DocumentText, load_document_text
from app.text_extract import extract_fields as extract_document_fields

router = APIRouter(tags=["resumes"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
EDIT_ROLES = (Role.ADMIN.value, Role.HIRING_MANAGER.value, Role.RECRUITER.value)
STAFF_ROLES = (*EDIT_ROLES, Role.INTERVIEWER.value, Role.AUDITOR.value)


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes, rejecting early rather than after the
    fact. A plain `await file.read()` would buffer the client's entire body
    into one `bytes` object first and only check its length afterward --
    Starlette's spooled temp file keeps that off the heap while the request
    is being parsed, but this line re-loads all of it into memory regardless
    of how large the upload actually was, so an oversized upload could still
    exhaust the process before the existing size check ever ran.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


class JobDescriptionCreate(BaseModel):
    title: str = PydField(min_length=1, max_length=300)
    raw_text: str = PydField(min_length=1)
    required_skills: list[str] = PydField(default_factory=list)
    preferred_skills: list[str] = PydField(default_factory=list)
    min_years_experience: int = PydField(default=0, ge=0, le=50)


class WeightProfileCreate(BaseModel):
    name: str = PydField(min_length=1, max_length=100)
    weights: dict[str, int]
    auto_reject_below: int = PydField(default=30, ge=0, le=100)
    hold_below: int = PydField(default=50, ge=0, le=100)
    highly_recommended_at: int = PydField(default=85, ge=0, le=100)


class ScoringRunRequest(BaseModel):
    resume_id: uuid.UUID
    weight_profile_id: uuid.UUID


class StructureRequest(BaseModel):
    field_name: str = PydField(min_length=1, max_length=64)


async def _load_requisition(db: AsyncSession, user: User, rid: uuid.UUID) -> Requisition:
    req = (await db.execute(select(Requisition).where(Requisition.id == rid))).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Requisition not found")
    dept = (
        await db.execute(select(Department).where(Department.id == req.department_id))
    ).scalar_one_or_none()
    if dept is None or dept.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return req


def _sniff_mime(filename: str, data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04") and filename.lower().endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/plain"


@router.post("/requisitions/{requisition_id}/job-description", status_code=201)
async def create_job_description(
    requisition_id: uuid.UUID,
    body: JobDescriptionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    jd = JobDescription(
        organization_id=user.organization_id,
        requisition_id=requisition_id,
        title=body.title,
        raw_text=body.raw_text,
        required_skills=[s.lower() for s in body.required_skills],
        preferred_skills=[s.lower() for s in body.preferred_skills],
        min_years_experience=body.min_years_experience,
    )
    db.add(jd)
    await db.flush()
    await record_event(
        db,
        action="job_description.created",
        entity_type="job_description",
        entity_id=jd.id,
        actor_id=user.id,
        organization_id=user.organization_id,
    )
    return {"id": str(jd.id), "title": jd.title}


@router.get("/requisitions/{requisition_id}/job-description")
async def get_job_description(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object] | None:
    await _load_requisition(db, user, requisition_id)
    jd = await _load_jd_for_resume(db, user, requisition_id)
    if jd is None:
        return None
    return {
        "id": str(jd.id),
        "title": jd.title,
        "raw_text": jd.raw_text,
        "required_skills": jd.required_skills,
        "preferred_skills": jd.preferred_skills,
        "min_years_experience": jd.min_years_experience,
    }


async def _load_jd_for_resume(
    db: AsyncSession, user: User, requisition_id: uuid.UUID
) -> JobDescription | None:
    jd = (
        await db.execute(
            select(JobDescription)
            .where(JobDescription.requisition_id == requisition_id)
            .order_by(JobDescription.version.desc(), JobDescription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if jd is not None and jd.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return jd


@router.post("/requisitions/{requisition_id}/resumes", status_code=201)
async def upload_resume(
    requisition_id: uuid.UUID,
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    data = await _read_capped(file, MAX_UPLOAD_BYTES)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    mime = _sniff_mime(file.filename or "", data)
    try:
        document: DocumentText = load_document_text(file.filename or "resume.txt", data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unreadable document: {exc}") from exc

    duplicate = (
        await db.execute(
            select(ResumeDocument).where(
                ResumeDocument.requisition_id == requisition_id,
                ResumeDocument.content_hash == document.content_hash,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Identical resume already uploaded")

    fields = extract_document_fields(document)
    email = next((f.value for f in fields if f.field_name == "email"), None)

    doc_row = ResumeDocument(
        organization_id=user.organization_id,
        requisition_id=requisition_id,
        filename=file.filename or "resume.txt",
        content_hash=document.content_hash,
        mime_type=mime,
        page_count=len(document.pages),
        full_text=document.full_text,
        candidate_email=email,
    )
    db.add(doc_row)
    await db.flush()

    for extracted in fields:
        db.add(
            ExtractedFieldRow(
                resume_id=doc_row.id,
                field_name=extracted.field_name,
                value=extracted.value,
                confidence=extracted.confidence,
                page_number=extracted.page_number,
                start_offset=extracted.start_offset,
                end_offset=extracted.end_offset,
                source_quote=extracted.source_quote,
                extractor=extracted.extractor,
            )
        )
    await record_event(
        db,
        action="resume.uploaded",
        entity_type="resume",
        entity_id=doc_row.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"filename": doc_row.filename, "field_count": len(fields)},
    )
    return {"id": str(doc_row.id), "field_count": len(fields), "page_count": len(document.pages)}


#: Field names whose *value* identifies the candidate (name/contact info),
#: as opposed to fields that carry the actual signal a blind first pass is
#: meant to focus reviewers on (skills, years, education, etc). Blind mode
#: redacts only these — same names DSAR erasure treats as PII (routers_dsar.py).
BLIND_SCREENING_FIELD_NAMES = frozenset({"email", "phone", "name", "full_name", "linkedin"})
BLIND_REDACTION_MARKER = "•••• hidden for blind screening ••••"


@router.get("/resumes/{resume_id}")
async def get_resume(
    resume_id: uuid.UUID,
    blind: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    doc = (
        await db.execute(select(ResumeDocument).where(ResumeDocument.id == resume_id))
    ).scalar_one_or_none()
    if doc is None or doc.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Resume not found")
    rows = (
        (
            await db.execute(
                select(ExtractedFieldRow)
                .where(ExtractedFieldRow.resume_id == resume_id)
                .order_by(ExtractedFieldRow.start_offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(doc.id),
        "filename": BLIND_REDACTION_MARKER if blind else doc.filename,
        "page_count": doc.page_count,
        "candidate_email": BLIND_REDACTION_MARKER if blind else doc.candidate_email,
        "blind": blind,
        "fields": [
            {
                "field_name": row.field_name,
                "value": (
                    BLIND_REDACTION_MARKER
                    if blind and row.field_name in BLIND_SCREENING_FIELD_NAMES
                    else row.value
                ),
                "confidence": row.confidence,
                "page_number": row.page_number,
                "start_offset": row.start_offset,
                "end_offset": row.end_offset,
                "source_quote": (
                    BLIND_REDACTION_MARKER
                    if blind and row.field_name in BLIND_SCREENING_FIELD_NAMES
                    else row.source_quote
                ),
                "extractor": row.extractor,
            }
            for row in rows
        ],
    }


@router.post("/requisitions/{requisition_id}/weight-profiles", status_code=201)
async def create_weight_profile(
    requisition_id: uuid.UUID,
    body: WeightProfileCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    try:
        validate_profile(body.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_count = len(
        (
            await db.execute(
                select(WeightProfileRow).where(
                    WeightProfileRow.organization_id == user.organization_id,
                    WeightProfileRow.name == body.name,
                )
            )
        )
        .scalars()
        .all()
    )
    profile = WeightProfileRow(
        organization_id=user.organization_id,
        name=body.name,
        version=existing_count + 1,
        weights=body.weights,
        auto_reject_below=body.auto_reject_below,
        hold_below=body.hold_below,
        highly_recommended_at=body.highly_recommended_at,
        created_by=user.id,
    )
    db.add(profile)
    await db.flush()
    await record_event(
        db,
        action="weight_profile.created",
        entity_type="weight_profile",
        entity_id=profile.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"name": body.name, "version": profile.version},
    )
    return {"id": str(profile.id), "name": profile.name, "version": profile.version}


async def _gateway_dimension(
    settings: Settings,
    dimension: str,
    jd_clause: str,
    candidate_spans: str,
    seed_key: str,
) -> DimensionInput:
    if not settings.ai_gateway_url:
        raise HTTPException(status_code=503, detail="AI gateway not configured")
    try:
        async with httpx.AsyncClient(base_url=settings.ai_gateway_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/generate",
                json={
                    "prompt_id": "dimension_score",
                    "response_model": "DimensionScore",
                    "inputs": {
                        "dimension": dimension,
                        "score_range_note": "0-100",
                        "jd_clause": jd_clause,
                        "candidate_spans": candidate_spans,
                    },
                    "seed_key": seed_key,
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"AI gateway unreachable: {exc}") from exc

    body = response.json()
    data = body["data"]
    return DimensionInput(
        dimension=dimension,
        score=int(data["score"]),
        evidence_refs=(
            f"gateway:{body['prompt_version']}:{body['model_id']}",
            *data["cited_span_ids"],
        ),
        rationale=str(data["rationale"]),
    )


def _profile_from_row(row: WeightProfileRow) -> WeightProfile:
    return WeightProfile(
        name=row.name,
        version=row.version,
        weights=dict(row.weights),
        auto_reject_below=int(row.auto_reject_below),
        hold_below=int(row.hold_below),
        highly_recommended_at=int(row.highly_recommended_at),
    )


@router.post("/requisitions/{requisition_id}/scoring-runs", status_code=201)
async def create_scoring_run(
    request: Request,
    requisition_id: uuid.UUID,
    body: ScoringRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDIT_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)

    doc = (
        await db.execute(select(ResumeDocument).where(ResumeDocument.id == body.resume_id))
    ).scalar_one_or_none()
    if (
        doc is None
        or doc.organization_id != user.organization_id
        or doc.requisition_id != requisition_id
    ):
        raise HTTPException(status_code=404, detail="Resume not found")

    jd = await _load_jd_for_resume(db, user, requisition_id)
    if jd is None:
        raise HTTPException(status_code=400, detail="No job description on this requisition")

    profile_row = (
        await db.execute(
            select(WeightProfileRow).where(WeightProfileRow.id == body.weight_profile_id)
        )
    ).scalar_one_or_none()
    if profile_row is None or profile_row.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Weight profile not found")
    profile = _profile_from_row(profile_row)

    field_rows = (
        (await db.execute(select(ExtractedFieldRow).where(ExtractedFieldRow.resume_id == doc.id)))
        .scalars()
        .all()
    )
    fields = [ExtractedFieldLike(row.field_name, row.value) for row in field_rows]

    requirements = JobRequirements(
        required_skills=frozenset(jd.required_skills or []),
        preferred_skills=frozenset(jd.preferred_skills or []),
        min_years_experience=int(jd.min_years_experience),
    )
    checks = run_match_checks(fields, requirements)
    checks_payload = to_payload(checks)
    technical = technical_dimension_from_checks(match_ratio(checks))

    span_summary = "\n".join(f"{row.field_name}: {row.source_quote}" for row in field_rows[:12])
    settings = get_app_settings(request)
    dimensions: list[DimensionInput] = [technical]
    for dim in sorted(DIMENSION_NAMES - {"technical"}):
        dimensions.append(
            await _gateway_dimension(
                settings,
                dim,
                jd.raw_text[:500],
                span_summary,
                seed_key=f"{doc.content_hash}:{profile.fingerprint}:{dim}",
            )
        )

    total = compute_total_score(dimensions, profile)
    verdict = assign_verdict(total, profile)
    fingerprint = run_fingerprint(doc.content_hash, checks_payload, dimensions, profile)

    run_row = ScoringRunRow(
        organization_id=user.organization_id,
        requisition_id=requisition_id,
        resume_id=doc.id,
        weight_profile_id=profile_row.id,
        total_score=total,
        verdict=verdict,
        checks_payload=checks_payload,
        dimensions_payload=[
            {
                "dimension": d.dimension,
                "score": d.score,
                "evidence_refs": list(d.evidence_refs),
                "rationale": d.rationale,
            }
            for d in dimensions
        ],
        run_fingerprint=fingerprint,
    )
    db.add(run_row)
    await db.flush()
    await record_event(
        db,
        action="scoring_run.created",
        entity_type="scoring_run",
        entity_id=run_row.id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"resume_id": str(doc.id), "total_score": total, "verdict": verdict},
    )
    return {
        "id": str(run_row.id),
        "total_score": total,
        "verdict": verdict,
        "run_fingerprint": fingerprint,
        "checks": checks_payload,
        "dimensions": run_row.dimensions_payload,
    }


class ExtractedFieldLike:
    def __init__(self, field_name: str, value: str) -> None:
        self.field_name = field_name
        self.value = value


def _summarize_run(run: ScoringRunRow | None) -> dict[str, object] | None:
    if run is None:
        return None
    return {
        "run_id": str(run.id),
        "total_score": run.total_score,
        "verdict": run.verdict,
        "run_fingerprint": run.run_fingerprint,
    }


@router.get("/requisitions/{requisition_id}/candidates")
async def list_candidates(
    requisition_id: uuid.UUID,
    blind: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    docs = (
        (
            await db.execute(
                select(ResumeDocument)
                .where(ResumeDocument.requisition_id == requisition_id)
                .order_by(ResumeDocument.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (
            await db.execute(
                select(ScoringRunRow)
                .where(ScoringRunRow.requisition_id == requisition_id)
                .order_by(ScoringRunRow.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    latest_by_resume: dict[str, ScoringRunRow] = {}
    for run in runs:
        key = str(run.resume_id)
        if key not in latest_by_resume:
            latest_by_resume[key] = run

    return {
        "candidates": [
            {
                "resume_id": str(doc.id),
                "filename": (BLIND_REDACTION_MARKER if blind else doc.filename),
                "candidate_email": (None if blind else doc.candidate_email),
                "created_at": doc.created_at.isoformat(),
                "latest_run": _summarize_run(latest_by_resume.get(str(doc.id))),
            }
            for doc in docs
        ],
        "blind": blind,
    }


@router.get("/requisitions/{requisition_id}/scoring-runs")
async def list_scoring_runs(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    runs = (
        (
            await db.execute(
                select(ScoringRunRow)
                .where(ScoringRunRow.requisition_id == requisition_id)
                .order_by(ScoringRunRow.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return {
        "runs": [
            {
                "id": str(r.id),
                "resume_id": str(r.resume_id),
                "total_score": r.total_score,
                "verdict": r.verdict,
                "run_fingerprint": r.run_fingerprint,
            }
            for r in runs
        ]
    }


@router.get("/requisitions/{requisition_id}/scoring-audit")
async def get_scoring_audit(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    """Deterministic scoring-consistency audit — see scoring_audit.py's
    module docstring for why this is scoped to consistency checks rather
    than a demographic disparate-impact analysis (ADR-023)."""
    await _load_requisition(db, user, requisition_id)
    rows = (
        (
            await db.execute(
                select(ScoringRunRow).where(ScoringRunRow.requisition_id == requisition_id)
            )
        )
        .scalars()
        .all()
    )
    facts = [
        ScoringRunFacts(
            resume_id=str(r.resume_id),
            weight_profile_id=str(r.weight_profile_id),
            total_score=r.total_score,
            verdict=r.verdict,
            run_fingerprint=r.run_fingerprint,
            dimensions_payload=r.dimensions_payload,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    findings = run_audit(facts)
    return {
        "runs_analyzed": len(facts),
        "findings": [
            {
                "kind": f.kind,
                "severity": f.severity,
                "detail": f.detail,
                "resume_ids": f.resume_ids,
            }
            for f in findings
        ],
    }
