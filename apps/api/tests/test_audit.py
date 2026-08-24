import uuid

from app.audit import compute_entry_hash, verify_chain
from app.models import AuditEvent, utcnow


def _event(**overrides: object) -> AuditEvent:
    defaults: dict = {
        "action": "test.action",
        "entity_type": "test",
        "entity_id": uuid.uuid4(),
        "actor_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "payload": {"k": "v"},
        "occurred_at": utcnow(),
        "prev_hash": None,
    }
    defaults.update(overrides)
    event = AuditEvent(**defaults)
    event.entry_hash = compute_entry_hash(event)
    return event


def test_single_event_chain_is_intact() -> None:
    assert verify_chain([_event()])


def test_multi_event_chain_links_hashes() -> None:
    first = _event()
    second = _event(prev_hash=first.entry_hash)
    third = _event(prev_hash=second.entry_hash)
    assert verify_chain([first, second, third])


def test_tampered_payload_breaks_chain() -> None:
    first = _event()
    second = _event(prev_hash=first.entry_hash)
    assert verify_chain([first, second])
    second.payload = {"k": "tampered"}
    assert not verify_chain([first, second])


def test_broken_link_detected() -> None:
    first = _event()
    second = _event(prev_hash="0" * 64)
    assert not verify_chain([first, second])


def test_hash_stable_across_calls() -> None:
    event = _event()
    assert compute_entry_hash(event) == compute_entry_hash(event)
