from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from app.scheduling import AvailabilityRule, generate_slots

NY = "America/New_York"


def _rule(**overrides: object) -> AvailabilityRule:
    defaults: dict = {
        "local_start": time(9, 0),
        "local_end": time(12, 0),
        "duration_minutes": 60,
        "buffer_minutes": 0,
    }
    defaults.update(overrides)
    return AvailabilityRule(**defaults)


def test_plain_week_generates_expected_slots() -> None:
    slots = generate_slots(_rule(), date(2026, 6, 1), date(2026, 6, 5), NY)
    assert len(slots) == 15
    assert all(slot.start_utc.tzinfo is not None for slot in slots)
    first = slots[0]
    assert first.start_utc.utcoffset() == timedelta(0)
    assert first.start_utc.date() == date(2026, 6, 1)
    local_first = first.start_utc.astimezone(ZoneInfo(NY))
    assert (local_first.hour, local_first.minute) == (9, 0)


def test_spring_forward_gap_has_no_two_thirty_slot() -> None:
    slots = generate_slots(
        _rule(
            local_start=time(1, 30),
            local_end=time(3, 30),
            duration_minutes=30,
            weekend_days=frozenset(),
        ),
        date(2026, 3, 8),
        date(2026, 3, 8),
        NY,
    )
    assert len(slots) == 2

    wall_times = sorted(slot.start_utc.astimezone(ZoneInfo(NY)).strftime("%H:%M") for slot in slots)
    assert wall_times == ["01:30", "03:00"]
    durations_ok = all((slot.end_utc - slot.start_utc) == timedelta(minutes=30) for slot in slots)
    assert durations_ok


def test_fall_back_does_not_duplicate_wall_times() -> None:
    slots = generate_slots(
        _rule(
            local_start=time(1, 0),
            local_end=time(2, 0),
            duration_minutes=30,
            weekend_days=frozenset(),
        ),
        date(2026, 11, 1),
        date(2026, 11, 1),
        NY,
    )
    keys = {slot.start_utc.isoformat() for slot in slots}
    assert len(keys) == len(slots) == 2


def test_weekends_and_blackout_dates_excluded() -> None:
    slots = generate_slots(
        _rule(excluded_dates=frozenset({date(2026, 7, 2)})),
        date(2026, 6, 29),
        date(2026, 7, 3),
        NY,
    )
    used_dates = {slot.start_utc.date() for slot in slots}
    assert date(2026, 7, 4) - timedelta(days=0) not in used_dates
    assert date(2026, 7, 2) not in used_dates
    assert date(2026, 6, 27) - timedelta(days=0) not in used_dates
    assert used_dates == {date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 3)}


def test_buffer_shifts_consecutive_starts() -> None:
    slots = generate_slots(
        _rule(buffer_minutes=10),
        date(2026, 6, 1),
        date(2026, 6, 1),
        NY,
    )
    starts = [slot.start_utc.astimezone(ZoneInfo(NY)).strftime("%H:%M") for slot in slots]
    assert starts == ["09:00", "10:10"]
    gaps = [(slots[i + 1].start_utc - slots[i].start_utc) for i in range(len(slots) - 1)]
    assert all(gap == timedelta(minutes=70) for gap in gaps)


def test_inverted_range_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_slots(_rule(), date(2026, 6, 5), date(2026, 6, 1), NY)


def test_slots_are_chronological_and_utc_anchored() -> None:
    slots = generate_slots(_rule(), date(2026, 6, 1), date(2026, 6, 2), "Asia/Kolkata")
    assert slots == sorted(slots, key=lambda s: s.start_utc)
    assert all(
        s.start_utc.tzinfo is not None and str(s.start_utc.tzinfo).endswith("UTC") for s in slots
    )
    assert slots[0].start_utc.utcoffset() == timedelta(0)
