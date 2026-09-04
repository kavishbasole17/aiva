"""Interview reminder emails (T-24h / T-1h), the one M7 gap ADR-031's email
delivery work explicitly left open (`docs/PLAN.md`'s M7 entry: "needs a
scheduler, same gap ADR-029's retention job has").

Same shape as ADR-029's retention endpoint: an idempotent, staff-authenticated
POST that a real scheduler (cron, systemd timer, Kubernetes CronJob) is meant
to invoke periodically -- choosing and wiring that invocation is a deployment
decision this repo intentionally doesn't make (ADR-029's own reasoning, which
applies just as much here: no scheduler dependency exists in this codebase
yet, and this endpoint is designed to be trivially callable from whichever
one a deployer picks). Unlike retention, sending a reminder is not a
destructive action gated behind a `dry_run`-by-default policy question -- a
slot is either due for a reminder it hasn't received or it isn't, so this
runs by default and reports what it sent.

A slot is due for its 24h (or 1h) reminder once `start_at` is within that
window of "now" -- not only exactly at the boundary -- so a deployer running
this every 15-30 minutes (or even much less often) still catches everything
that's due since the last run, and a slot whose window has already fully
passed without a run (start_at in the past) is treated as still-eligible
once rather than silently skipped, since a late reminder is still useful and
the sent-at column makes re-sends impossible either way.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_event
from app.deps import get_db, get_email_provider, require_roles
from app.email import EmailProvider
from app.models import InterviewSlot, Role, User

router = APIRouter(tags=["reminders"])

REMINDER_ROLES = (
    Role.ADMIN.value,
    Role.HIRING_MANAGER.value,
    Role.RECRUITER.value,
)

WINDOWS = (
    ("24h", timedelta(hours=24), "reminder_24h_sent_at"),
    ("1h", timedelta(hours=1), "reminder_1h_sent_at"),
)


class ReminderSent(BaseModel):
    slot_id: str
    candidate_email: str
    start_at: str
    window: str


class ReminderRunResponse(BaseModel):
    sent: list[ReminderSent]


@router.post("/orgs/{organization_id}/interview-reminders/run", response_model=ReminderRunResponse)
async def run_interview_reminders(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*REMINDER_ROLES)),
    email: EmailProvider = Depends(get_email_provider),
) -> ReminderRunResponse:
    if user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")

    now = datetime.now(UTC)
    slots = (
        await db.execute(
            select(InterviewSlot).where(
                InterviewSlot.organization_id == organization_id,
                InterviewSlot.status == "booked",
                InterviewSlot.booked_for_email.is_not(None),
            )
        )
    ).scalars()

    sent: list[ReminderSent] = []
    for slot in slots:
        for label, window, column in WINDOWS:
            if getattr(slot, column) is not None:
                continue
            if slot.start_at > now + window:
                continue
            to = slot.booked_for_email
            if to is None:
                continue
            await email.send(
                to=to,
                subject=f"Reminder: your AIVA interview is in {label.replace('h', ' hour(s)')}",
                body=(
                    f"This is a reminder that your interview is scheduled for "
                    f"{slot.start_at.isoformat()} (UTC) to {slot.end_at.isoformat()} (UTC)."
                ),
            )
            setattr(slot, column, now)
            sent.append(
                ReminderSent(
                    slot_id=str(slot.id),
                    candidate_email=to,
                    start_at=slot.start_at.isoformat(),
                    window=label,
                )
            )

    if sent:
        await record_event(
            db,
            action="interview_reminders.run",
            entity_type="organization",
            entity_id=organization_id,
            actor_id=user.id,
            organization_id=organization_id,
            payload={"sent_count": len(sent)},
        )
    await db.flush()

    return ReminderRunResponse(sent=sent)
