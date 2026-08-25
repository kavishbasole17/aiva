from datetime import UTC, datetime

from app.ics import build_ics


def test_ics_structure_and_utc_formatting() -> None:
    start = datetime(2026, 7, 1, 13, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    ics = build_ics(
        uid="invite-123@aiva",
        summary="Interview: Senior Backend",
        description="Panel interview; bring questions.",
        start_utc=start,
        end_utc=end,
        organizer_email="recruiter@example.test",
        attendee_email="candidate@example.test",
    )
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert "PRODID:-//AIVA//Interview Scheduling//EN" in ics
    assert "DTSTART:20260701T130000Z\r\n" in ics
    assert "DTEND:20260701T140000Z\r\n" in ics
    assert "SUMMARY:Interview: Senior Backend" in ics
    assert "DESCRIPTION:Panel interview\\; bring questions." in ics
    assert "ORGANIZER;CN=recruiter@example.test:mailto:recruiter@example.test" in ics
    assert "ATTENDEE;RSVP=TRUE:mailto:candidate@example.test" in ics
    assert ics.endswith("END:VCALENDAR\r\n")


def test_ics_escapes_commas_and_newlines() -> None:
    ics = build_ics(
        uid="x@y",
        summary="A, B\nC",
        description="d",
        start_utc=datetime(2026, 7, 1, tzinfo=UTC),
        end_utc=datetime(2026, 7, 2, tzinfo=UTC),
        organizer_email="o@e.test",
        attendee_email="a@e.test",
    )
    assert "SUMMARY:A\\, B\\nC" in ics


def test_naive_datetimes_treated_as_utc() -> None:
    ics = build_ics(
        uid="u@a",
        summary="s",
        description="d",
        start_utc=datetime(2026, 7, 1, 10, 0),
        end_utc=datetime(2026, 7, 1, 11, 0),
        organizer_email="o@e.test",
        attendee_email="a@e.test",
    )
    assert "DTSTART:20260701T100000Z" in ics
