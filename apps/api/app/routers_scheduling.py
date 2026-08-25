import uuid
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from pydantic import Field as PydField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_db, require_roles
from app.ics import build_ics
from app.models import InterviewSlot, Role, User
from app.scheduling import AvailabilityRule, generate_slots

router = APIRouter(tags=["scheduling"])

STAFF_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)


class SlotGenerationRequest(BaseModel):
    date_from: date
    date_to: date
    timezone_name: str = PydField(min_length=1, max_length=64)
    local_start: time
    local_end: time
    duration_minutes: int = PydField(default=45, ge=15, le=180)
    buffer_minutes: int = PydField(default=10, ge=0, le=60)
    excluded_dates: list[date] = PydField(default_factory=list)
    include_weekends: bool = False


class BookingRequest(BaseModel):
    candidate_email: EmailStr


async def _load_requisition(db: AsyncSession, user: User, rid: uuid.UUID) -> None:
    from app.routers_resume import _load_requisition as _load_scoped

    await _load_scoped(db, user, rid)


@router.post("/requisitions/{requisition_id}/slots/generate", status_code=201)
async def generate_requisition_slots(
    requisition_id: uuid.UUID,
    body: SlotGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    await _load_requisition(db, user, requisition_id)
    try:
        slots = generate_slots(
            AvailabilityRule(
                local_start=body.local_start,
                local_end=body.local_end,
                duration_minutes=body.duration_minutes,
                buffer_minutes=body.buffer_minutes,
                weekend_days=frozenset() if body.include_weekends else frozenset({5, 6}),
                excluded_dates=frozenset(body.excluded_dates),
            ),
            body.date_from,
            body.date_to,
            body.timezone_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid timezone: {body.timezone_name}"
        ) from exc

    existing = {
        row[0]
        for row in (
            await db.execute(
                select(InterviewSlot.start_at).where(
                    InterviewSlot.requisition_id == requisition_id,
                    InterviewSlot.status == "open",
                )
            )
        ).all()
    }

    created = 0
    for slot in slots:
        if slot.start_utc in existing:
            continue
        db.add(
            InterviewSlot(
                organization_id=user.organization_id,
                requisition_id=requisition_id,
                start_at=slot.start_utc,
                end_at=slot.end_utc,
            )
        )
        created += 1
    await db.flush()
    await record_event(
        db,
        action="slots.generated",
        entity_type="requisition",
        entity_id=requisition_id,
        actor_id=user.id,
        organization_id=user.organization_id,
        payload={"created": created, "timezone": body.timezone_name},
    )
    return {"created": created}


@router.get("/requisitions/{requisition_id}/slots")
async def list_slots(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    rows = (
        (
            await db.execute(
                select(InterviewSlot)
                .where(InterviewSlot.requisition_id == requisition_id)
                .order_by(InterviewSlot.start_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "slots": [
            {
                "id": str(row.id),
                "start_at": row.start_at.isoformat(),
                "end_at": row.end_at.isoformat(),
                "status": row.status,
                "booked_for_email": row.booked_for_email,
            }
            for row in rows
        ]
    }


@router.post("/slots/{slot_id}/book")
async def book_slot(
    slot_id: uuid.UUID,
    body: BookingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*STAFF_ROLES)),
) -> dict[str, object]:
    slot = (
        await db.execute(select(InterviewSlot).where(InterviewSlot.id == slot_id))
    ).scalar_one_or_none()
    if slot is None or slot.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot.status != "open":
        raise HTTPException(status_code=409, detail="Slot no longer available")

    slot.status = "booked"
    slot.booked_for_email = body.candidate_email.lower()
    await record_event(
        db,
        action="slot.booked",
        entity_type="interview_slot",
        entity_id=slot.id,
        actor_id=user.id,
        organization_id=slot.organization_id,
        payload={"candidate_email": slot.booked_for_email},
    )

    ics = build_ics(
        uid=f"slot-{slot.id}@aiva",
        summary="AIVA interview",
        description="Your interview slot confirmation.",
        start_utc=slot.start_at,
        end_utc=slot.end_at,
        organizer_email=user.email,
        attendee_email=slot.booked_for_email or "",
    )
    return {"id": str(slot.id), "status": slot.status, "ics": ics}
