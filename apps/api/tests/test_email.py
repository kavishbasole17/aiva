"""Unit tests for the pluggable email provider (app/email.py).

LogEmailProvider is tested via structlog's capture fixture; SmtpEmailProvider
by mocking smtplib.SMTP directly (no real network connection, no real SMTP
server needed) -- proves the right calls happen with the right arguments,
same discipline as test_anthropic_backend.py mocking the Anthropic SDK.
"""

from unittest.mock import MagicMock, patch

import pytest
import structlog

from app.email import LogEmailProvider, SmtpEmailProvider, build_email_provider


async def test_log_provider_logs_instead_of_sending() -> None:
    provider = LogEmailProvider()
    with structlog.testing.capture_logs() as captured:
        await provider.send(
            to="candidate@example.test",
            subject="Test subject",
            body="Test body",
            attachment=("invite.ics", b"BEGIN:VCALENDAR"),
        )
    assert len(captured) == 1
    entry = captured[0]
    assert entry["event"] == "email.would_send"
    assert entry["to"] == "candidate@example.test"
    assert entry["subject"] == "Test subject"
    assert entry["attachment_filename"] == "invite.ics"
    assert entry["attachment_bytes"] == len(b"BEGIN:VCALENDAR")


async def test_log_provider_without_attachment() -> None:
    provider = LogEmailProvider()
    with structlog.testing.capture_logs() as captured:
        await provider.send(to="a@example.test", subject="s", body="b")
    assert captured[0]["attachment_filename"] is None
    assert captured[0]["attachment_bytes"] == 0


async def test_smtp_provider_sends_via_smtplib() -> None:
    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_class:
        provider = SmtpEmailProvider(
            host="smtp.example.test",
            port=587,
            username="user",
            password="pass",
            from_addr="no-reply@aiva.test",
            use_tls=True,
        )
        await provider.send(
            to="candidate@example.test",
            subject="Interview confirmed",
            body="See attached invite.",
            attachment=("invite.ics", b"BEGIN:VCALENDAR\nEND:VCALENDAR"),
        )

    mock_smtp_class.assert_called_once_with("smtp.example.test", 587, timeout=10)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("user", "pass")
    assert mock_smtp_instance.send_message.call_count == 1
    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == "candidate@example.test"
    assert sent_message["Subject"] == "Interview confirmed"
    assert sent_message["From"] == "no-reply@aiva.test"
    # A message with an attachment becomes multipart/mixed; the plain-text
    # body lives in the message's own "body" part, not at the top level.
    body_part = sent_message.get_body(preferencelist=("plain",))
    assert body_part is not None
    assert body_part.get_content().strip() == "See attached invite."
    attachments = list(sent_message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "invite.ics"


async def test_smtp_provider_skips_login_without_username() -> None:
    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_instance.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        provider = SmtpEmailProvider(
            host="smtp.example.test",
            port=25,
            username="",
            password="",
            from_addr="no-reply@aiva.test",
            use_tls=False,
        )
        await provider.send(to="a@example.test", subject="s", body="b")

    mock_smtp_instance.login.assert_not_called()
    mock_smtp_instance.starttls.assert_not_called()


def test_build_email_provider_log_default() -> None:
    provider = build_email_provider("log", "", 587, "", "", "no-reply@aiva.test", True)
    assert isinstance(provider, LogEmailProvider)


def test_build_email_provider_smtp_requires_host() -> None:
    with pytest.raises(ValueError, match="AIVA_EMAIL_SMTP_HOST"):
        build_email_provider("smtp", "", 587, "", "", "no-reply@aiva.test", True)


def test_build_email_provider_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown email backend"):
        build_email_provider("carrier-pigeon", "", 587, "", "", "no-reply@aiva.test", True)
