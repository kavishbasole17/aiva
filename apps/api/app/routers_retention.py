"""Data retention: automated erasure of candidate data past a configurable
retention window (M12 scope), built directly on the DSAR erasure logic
(`routers_dsar.py`) rather than duplicating it — same redaction fields, same
"overwrite in place, never delete the row" discipline, same audit trail.

Retention policy scope, stated plainly rather than left implicit: this
implementation ages candidates off by their earliest resume upload date
(`ResumeDocument.created_at`), organization-configurable via
`retention_days` on each call (no fixed default is asserted as legally
correct for any jurisdiction — that is a policy decision for the operating
organization, not something to hardcode here). It does not attempt to
model "is this candidate still in an active pipeline" — an operator relying
on this for real compliance should confirm no open requisition still needs
this data before running it for real, not just trust the age cutoff alone.
`dry_run` (default true) exists specifically so that check can happen before
anything is actually erased.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_db, require_roles
from app.models import ResumeDocument, Role, User
from app.routers_dsar import _apply_erasure, _find_candidate_records

router = APIRouter(tags=["retention"])

RETENTION_ROLES = (Role.ADMIN.value,)


class RetentionRunRequest(BaseModel):
    retention_days: int = Field(ge=0, le=3650)
    dry_run: bool = True
    max_candidates: int = Field(default=500, ge=1, le=5000)


class RetentionCandidatePreview(BaseModel):
    candidate_email: str
    earliest_resume_at: str


class RetentionRunResponse(BaseModel):
    dry_run: bool
    cutoff: str
    eligible_count: int
    erased_count: int
    candidates: list[RetentionCandidatePreview]


@router.post("/orgs/{organization_id}/retention/run", response_model=RetentionRunResponse)
async def run_retention(
    organization_id: uuid.UUID,
    body: RetentionRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*RETENTION_ROLES)),
) -> RetentionRunResponse:
    if user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")

    cutoff = datetime.now(UTC) - timedelta(days=body.retention_days)

    rows = (
        await db.execute(
            select(
                ResumeDocument.candidate_email,
                ResumeDocument.created_at,
            )
            .where(
                ResumeDocument.organization_id == organization_id,
                ResumeDocument.candidate_email.is_not(None),
                ResumeDocument.created_at < cutoff,
            )
            .order_by(ResumeDocument.created_at)
        )
    ).all()

    # One candidate can have multiple resumes across requisitions; keep the
    # earliest per email as the reported anchor date and dedupe the work.
    earliest_by_email: dict[str, datetime] = {}
    for email, created_at in rows:
        normalized = email.strip().lower()
        if normalized not in earliest_by_email or created_at < earliest_by_email[normalized]:
            earliest_by_email[normalized] = created_at

    candidates = sorted(earliest_by_email.items(), key=lambda pair: pair[1])[: body.max_candidates]

    erased_count = 0
    if not body.dry_run:
        for email, _earliest in candidates:
            records = await _find_candidate_records(db, organization_id, email)
            if not any(records.values()):
                continue
            _apply_erasure(records)
            erased_count += 1
        if candidates:
            await record_event(
                db,
                action="retention.auto_erase_run",
                entity_type="organization",
                entity_id=organization_id,
                actor_id=user.id,
                organization_id=organization_id,
                payload={
                    "retention_days": body.retention_days,
                    "cutoff": cutoff.isoformat(),
                    "eligible_count": len(candidates),
                    "erased_count": erased_count,
                },
            )
        await db.flush()

    return RetentionRunResponse(
        dry_run=body.dry_run,
        cutoff=cutoff.isoformat(),
        eligible_count=len(candidates),
        erased_count=erased_count,
        candidates=[
            RetentionCandidatePreview(
                candidate_email=email, earliest_resume_at=earliest.isoformat()
            )
            for email, earliest in candidates
        ],
    )
