import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, utcnow


def compute_entry_hash(event: AuditEvent) -> str:
    canonical = json.dumps(
        {
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "organization_id": str(event.organization_id) if event.organization_id else None,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id) if event.entity_id else None,
            "payload": event.payload,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "prev_hash": event.prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_event(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    payload: dict[str, object] | None = None,
) -> AuditEvent:
    last = (
        await session.execute(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(1))
    ).scalar_one_or_none()

    event = AuditEvent(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        organization_id=organization_id,
        payload=payload or {},
        prev_hash=last.entry_hash if last else None,
        occurred_at=utcnow(),
    )
    event.entry_hash = compute_entry_hash(event)
    session.add(event)
    await session.flush()
    return event


def verify_chain(events: list[AuditEvent]) -> bool:
    for index, event in enumerate(events):
        expected_prev = events[index - 1].entry_hash if index > 0 else None
        if event.prev_hash != expected_prev:
            return False
        if compute_entry_hash(event) != event.entry_hash:
            return False
    return True
