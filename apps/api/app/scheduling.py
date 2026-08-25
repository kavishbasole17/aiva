"""DST-correct interview slot generation.

All arithmetic happens in the recruiter's local timezone via zoneinfo so
spring-forward gaps and fall-back overlaps are handled by construction;
results are emitted as UTC.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class AvailabilityRule:
    local_start: time
    local_end: time
    duration_minutes: int
    buffer_minutes: int = 0
    weekend_days: frozenset[int] = frozenset({5, 6})
    excluded_dates: frozenset[date] = frozenset()


@dataclass(frozen=True)
class Slot:
    start_utc: datetime
    end_utc: datetime

    @property
    def key(self) -> str:
        return self.start_utc.isoformat()


def _is_real_wall_time(naive: datetime, tz: ZoneInfo) -> bool:
    aware = naive.replace(tzinfo=tz)
    round_trip = aware.astimezone(ZoneInfo("UTC")).astimezone(tz)
    return round_trip.replace(tzinfo=None) == naive


def generate_slots(
    rule: AvailabilityRule,
    first_date: date,
    last_date: date,
    timezone_name: str,
) -> list[Slot]:
    if first_date > last_date:
        raise ValueError("first_date must be on or before last_date")
    tz = ZoneInfo(timezone_name)
    duration = timedelta(minutes=rule.duration_minutes)
    buffer_ = timedelta(minutes=rule.buffer_minutes)

    slots: list[Slot] = []
    seen_starts: set[str] = set()
    current = first_date
    while current <= last_date:
        if current.weekday() not in rule.weekend_days and current not in rule.excluded_dates:
            day_start = datetime.combine(current, rule.local_start)
            day_end = datetime.combine(current, rule.local_end)
            cursor = day_start
            while cursor + duration <= day_end:
                if _is_real_wall_time(cursor, tz):
                    start_utc = cursor.replace(tzinfo=tz).astimezone(ZoneInfo("UTC"))
                    end_utc = (cursor + duration).replace(tzinfo=tz).astimezone(ZoneInfo("UTC"))
                    candidate = Slot(start_utc=start_utc, end_utc=end_utc)
                    if candidate.key not in seen_starts:
                        seen_starts.add(candidate.key)
                        slots.append(candidate)
                cursor += duration + buffer_
        current = current + timedelta(days=1)

    slots.sort(key=lambda s: s.start_utc)
    return slots


def to_utc(dt_local: datetime, timezone_name: str) -> datetime:
    return dt_local.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC)


def ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
