from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.retention import latest_activity_at

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _records(**overrides: list[object]) -> dict[str, list[object]]:
    base: dict[str, list[object]] = {
        "resumes": [],
        "invites": [],
        "responses": [],
        "sessions": [],
        "evaluations": [],
    }
    base.update(overrides)
    return base


def test_latest_activity_is_none_with_no_timestamped_records() -> None:
    assert latest_activity_at(_records()) is None


def test_latest_activity_picks_the_most_recent_across_record_kinds() -> None:
    old = NOW - timedelta(days=400)
    recent = NOW - timedelta(days=1)
    records = _records(
        resumes=[SimpleNamespace(created_at=old)],
        sessions=[SimpleNamespace(finished_at=None, started_at=None, created_at=recent)],
    )
    assert latest_activity_at(records) == recent


def test_session_prefers_finished_over_started_over_created() -> None:
    finished = NOW - timedelta(days=1)
    started = NOW - timedelta(days=2)
    created = NOW - timedelta(days=3)
    records = _records(
        sessions=[SimpleNamespace(finished_at=finished, started_at=started, created_at=created)]
    )
    assert latest_activity_at(records) == finished

    records = _records(
        sessions=[SimpleNamespace(finished_at=None, started_at=started, created_at=created)]
    )
    assert latest_activity_at(records) == started


def test_invite_prefers_completed_over_created() -> None:
    completed = NOW - timedelta(days=1)
    created = NOW - timedelta(days=10)
    records = _records(invites=[SimpleNamespace(completed_at=completed, created_at=created)])
    assert latest_activity_at(records) == completed

    records = _records(invites=[SimpleNamespace(completed_at=None, created_at=created)])
    assert latest_activity_at(records) == created


def test_a_single_recent_record_keeps_the_candidate_exempt() -> None:
    # A candidate with an old resume but a brand-new interview session should
    # not look stale overall — "latest" activity is what matters, not any one
    # record kind in isolation.
    old = NOW - timedelta(days=1000)
    recent = NOW - timedelta(hours=1)
    records = _records(
        resumes=[SimpleNamespace(created_at=old)],
        evaluations=[SimpleNamespace(created_at=recent)],
    )
    activity = latest_activity_at(records)
    assert activity == recent
    assert activity > NOW - timedelta(days=730)
