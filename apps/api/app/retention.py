"""M12 retention jobs: automated PII erasure once a candidate's data has
aged past the organization's retention window.

This is deliberately *not* a new deletion path — it drives the exact same
`dsar_service.apply_erasure` an admin-initiated DSAR erasure uses (migration
0011, ADR-022), just triggered by age instead of a specific request. A
candidate is only swept once every one of their known records — resume,
questionnaire invite, interview session, evaluation report — predates the
cutoff; a single recent record (e.g. a resume re-upload for a new
requisition) keeps the whole candidate exempt, matching how a person would
reasonably expect "delete data N days after my last interaction" to behave
rather than "delete each row N days after it was created."

No I/O beyond straightforward SQLAlchemy reads here — `run_retention_sweep`
is the only entry point with a side effect (via `apply_erasure`), and it
takes an already-open, RLS-bound session so it can be driven from an HTTP
endpoint (`routers_dsar.run_retention`) today and from a scheduled job
(Helm CronJob, M12) without any call-site change once that lands.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dsar_service import apply_erasure, find_candidate_records
from app.models import InterviewSession, QuestionnaireInvite, ResumeDocument

# Emails already rewritten by a prior DSAR/retention erasure — never re-swept.
_REDACTED_EMAIL_SUFFIX = "@invalid.example"


def latest_activity_at(records: dict[str, list[Any]]) -> datetime | None:
    """The most recent timestamp across every record found for a candidate.

    `None` means no timestamped activity was found at all (shouldn't happen
    for a non-empty record set, since every table here carries a timestamp),
    treated as "not eligible" by the caller rather than "infinitely stale."
    """
    timestamps: list[datetime] = []
    for resume in records["resumes"]:
        timestamps.append(resume.created_at)
    for invite in records["invites"]:
        timestamps.append(invite.completed_at or invite.created_at)
    for response in records["responses"]:
        timestamps.append(response.updated_at)
    for session in records["sessions"]:
        timestamps.append(session.finished_at or session.started_at or session.created_at)
    for evaluation in records["evaluations"]:
        timestamps.append(evaluation.created_at)
    return max(timestamps) if timestamps else None


async def _distinct_candidate_emails(db: AsyncSession, organization_id: uuid.UUID) -> set[str]:
    emails: set[str] = set()

    resume_rows = await db.execute(
        select(ResumeDocument.candidate_email).where(
            ResumeDocument.organization_id == organization_id,
            ResumeDocument.candidate_email.is_not(None),
        )
    )
    emails.update(e for e in resume_rows.scalars().all() if e)

    invite_rows = await db.execute(
        select(QuestionnaireInvite.candidate_email).where(
            QuestionnaireInvite.organization_id == organization_id
        )
    )
    emails.update(
        e for e in invite_rows.scalars().all() if e and not e.endswith(_REDACTED_EMAIL_SUFFIX)
    )

    session_rows = await db.execute(
        select(InterviewSession.candidate_email).where(
            InterviewSession.organization_id == organization_id
        )
    )
    emails.update(
        e for e in session_rows.scalars().all() if e and not e.endswith(_REDACTED_EMAIL_SUFFIX)
    )

    return {e.strip().lower() for e in emails}


async def run_retention_sweep(
    db: AsyncSession, organization_id: uuid.UUID, cutoff: datetime
) -> dict[str, object]:
    """Erase every candidate in `organization_id` whose latest known
    activity is strictly before `cutoff`. Returns an aggregate summary
    (never the raw emails — only their SHA-256 hashes, same discipline as
    the manual DSAR endpoints) suitable for both the API response and the
    audit event payload.
    """
    candidates_erased = 0
    total_counts: dict[str, int] = {}
    email_hashes: list[str] = []

    for email in sorted(await _distinct_candidate_emails(db, organization_id)):
        records = await find_candidate_records(db, organization_id, email)
        if not any(records.values()):
            continue
        activity = latest_activity_at(records)
        if activity is None or activity >= cutoff:
            continue

        counts = apply_erasure(records)
        candidates_erased += 1
        email_hashes.append(hashlib.sha256(email.encode("utf-8")).hexdigest())
        for key, value in counts.items():
            total_counts[key] = total_counts.get(key, 0) + value

    return {
        "candidates_erased": candidates_erased,
        "record_counts": total_counts,
        "candidate_email_sha256s": email_hashes,
    }


__all__ = ["latest_activity_at", "run_retention_sweep"]
