"""Local .ics generation — no external calendar APIs (constraint §3)."""

from datetime import UTC, datetime


def _fmt_utc(value: datetime) -> str:
    utc_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    return utc_value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(
    *,
    uid: str,
    summary: str,
    description: str,
    start_utc: datetime,
    end_utc: datetime,
    organizer_email: str,
    attendee_email: str,
    location: str = "AIVA video interview room",
) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AIVA//Interview Scheduling//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{_escape(uid)}",
        f"DTSTAMP:{_fmt_utc(datetime.now(UTC))}",
        f"DTSTART:{_fmt_utc(start_utc)}",
        f"DTEND:{_fmt_utc(end_utc)}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(description)}",
        f"LOCATION:{_escape(location)}",
        f"ORGANIZER;CN={_escape(organizer_email)}:mailto:{organizer_email}",
        f"ATTENDEE;RSVP=TRUE:mailto:{attendee_email}",
        "STATUS:TENTATIVE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"
