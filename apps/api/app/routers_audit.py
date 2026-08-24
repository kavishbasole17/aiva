from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_roles
from app.models import AuditEvent, Role, User

router = APIRouter(tags=["audit"])


@router.get("/audit-events")
async def list_audit_events(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN.value, Role.AUDITOR.value)),
) -> dict[str, object]:
    events = (
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.organization_id == user.organization_id)
                .order_by(AuditEvent.sequence.asc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    return {
        "events": [
            {
                "sequence": event.sequence,
                "occurred_at": event.occurred_at.isoformat(),
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": str(event.entity_id) if event.entity_id else None,
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "entry_hash": event.entry_hash,
                "prev_hash": event.prev_hash,
            }
            for event in events
        ]
    }


@router.get("/audit-events/verify")
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN.value, Role.AUDITOR.value)),
) -> dict[str, object]:
    from app.audit import verify_chain

    events = (
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.organization_id == user.organization_id)
                .order_by(AuditEvent.sequence.asc())
            )
        )
        .scalars()
        .all()
    )
    intact = verify_chain(list(events))
    return {"intact": intact, "event_count": len(events)}
