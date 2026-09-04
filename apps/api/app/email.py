"""Outbound email behind a pluggable interface -- same mock-now/real-later
precedent as every other external capability in this codebase (STT/TTS/LLM
backends in services/ai-gateway, ADR-017).

`LogEmailProvider` (default) writes a structured log line instead of
sending anything -- exactly what the product spec called for ("an email
interface with a log-based stub implementation, swappable for a real
provider later"), not a silent no-op: an operator can see every email that
*would* have been sent, and the send-vs-log decision is made by
configuration, not code, so wiring in `SmtpEmailProvider` later needs no
call-site changes.

`SmtpEmailProvider` is a real implementation using stdlib `smtplib` --
genuinely sends mail given real SMTP credentials, not another mock.
"""

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

import structlog

logger = structlog.get_logger(__name__)


class EmailProvider(ABC):
    @abstractmethod
    async def send(
        self, to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None
    ) -> None:
        """attachment, if given, is (filename, content_bytes) -- e.g. a .ics invite."""


class LogEmailProvider(EmailProvider):
    """Default. Logs what would be sent instead of sending it."""

    async def send(
        self, to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None
    ) -> None:
        logger.info(
            "email.would_send",
            to=to,
            subject=subject,
            body_preview=body[:200],
            attachment_filename=attachment[0] if attachment else None,
            attachment_bytes=len(attachment[1]) if attachment else 0,
        )


class SmtpEmailProvider(EmailProvider):
    """Real delivery via stdlib smtplib. Synchronous smtplib call is run in
    a thread so it never blocks the event loop."""

    def __init__(
        self, host: str, port: int, username: str, password: str, from_addr: str, use_tls: bool
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls

    def _send_sync(
        self, to: str, subject: str, body: str, attachment: tuple[str, bytes] | None
    ) -> None:
        message = EmailMessage()
        message["From"] = self.from_addr
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if attachment is not None:
            filename, content = attachment
            message.add_attachment(content, maintype="text", subtype="calendar", filename=filename)

        with smtplib.SMTP(self.host, self.port, timeout=10) as client:
            if self.use_tls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(message)

    async def send(
        self, to: str, subject: str, body: str, attachment: tuple[str, bytes] | None = None
    ) -> None:
        import asyncio

        await asyncio.to_thread(self._send_sync, to, subject, body, attachment)


def build_email_provider(
    backend: str, host: str, port: int, username: str, password: str, from_addr: str, use_tls: bool
) -> EmailProvider:
    if backend == "log":
        return LogEmailProvider()
    if backend == "smtp":
        if not host:
            raise ValueError("AIVA_EMAIL_SMTP_HOST required for the smtp email backend")
        return SmtpEmailProvider(host, port, username, password, from_addr, use_tls)
    raise ValueError(f"Unknown email backend: {backend}")


__all__ = [
    "EmailProvider",
    "LogEmailProvider",
    "SmtpEmailProvider",
    "build_email_provider",
]
