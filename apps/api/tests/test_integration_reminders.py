"""Interview reminder job (ADR-034) against a live stack.

Proves the timing behavior that actually matters: a booked slot whose start
time has entered a reminder window gets exactly one reminder per window
(never a duplicate on a second run), a slot far outside any window is left
alone, and one organization's run never touches another organization's
slots. Slot start times are computed relative to real wall-clock time at
test run (via the pure `generate_slots` arithmetic, not real waiting) so the
test is deterministic and fast.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.environ.get("AIVA_INTEGRATION") != "1",
    reason="integration compose stack not running (set AIVA_INTEGRATION=1)",
)

PASSWORD = "long-enough-password-123"


@pytest.fixture
async def http() -> httpx.AsyncClient:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _staff_context(http: httpx.AsyncClient, label: str) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"remind-{label}-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Remind Org {label} {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, org.json()[
        "organization_id"
    ]


async def _requisition(http: httpx.AsyncClient, headers: dict[str, str], org_id: str) -> str:
    dept = await http.post(f"/orgs/{org_id}/departments", json={"name": "Eng"}, headers=headers)
    assert dept.status_code == 201, dept.text
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Backend Engineer", "department_id": dept.json()["id"]},
        headers=headers,
    )
    assert req.status_code == 201, req.text
    return str(req.json()["id"])


async def _book_slot_at(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    rid: str,
    offset: timedelta,
    candidate_email: str,
) -> str:
    """Generates a single slot starting `offset` from real now (UTC) and books it."""
    target = datetime.now(UTC) + offset
    generated = await http.post(
        f"/requisitions/{rid}/slots/generate",
        json={
            "date_from": target.date().isoformat(),
            "date_to": target.date().isoformat(),
            "timezone_name": "UTC",
            "local_start": target.strftime("%H:%M:%S"),
            "local_end": (target + timedelta(minutes=15)).strftime("%H:%M:%S"),
            "duration_minutes": 15,
            "buffer_minutes": 0,
            "include_weekends": True,
        },
        headers=headers,
    )
    assert generated.status_code == 201, generated.text
    assert generated.json()["created"] == 1, generated.json()

    listed = await http.get(f"/requisitions/{rid}/slots", headers=headers)
    slot_id = next(s["id"] for s in listed.json()["slots"] if s["status"] == "open")
    booked = await http.post(
        f"/slots/{slot_id}/book",
        json={"candidate_email": candidate_email},
        headers=headers,
    )
    assert booked.status_code == 200, booked.text
    return str(slot_id)


async def test_due_slot_gets_both_windows_once_and_only_once(http: httpx.AsyncClient) -> None:
    headers, org_id = await _staff_context(http, "due")
    rid = await _requisition(http, headers, org_id)

    # 20 minutes out: inside both the 24h and 1h windows on the very first run.
    slot_id = await _book_slot_at(
        http, headers, rid, timedelta(minutes=20), "due-candidate@example.test"
    )

    first_run = await http.post(f"/orgs/{org_id}/interview-reminders/run", headers=headers)
    assert first_run.status_code == 200, first_run.text
    sent = first_run.json()["sent"]
    assert {entry["window"] for entry in sent if entry["slot_id"] == slot_id} == {"24h", "1h"}
    assert all(entry["candidate_email"] == "due-candidate@example.test" for entry in sent)

    # Re-running finds nothing left to send for this slot -- both columns are
    # now set, so it's correctly excluded rather than re-sent.
    second_run = await http.post(f"/orgs/{org_id}/interview-reminders/run", headers=headers)
    assert second_run.status_code == 200
    assert second_run.json()["sent"] == []


async def test_far_future_slot_not_yet_due(http: httpx.AsyncClient) -> None:
    headers, org_id = await _staff_context(http, "future")
    rid = await _requisition(http, headers, org_id)

    await _book_slot_at(http, headers, rid, timedelta(days=3), "future-candidate@example.test")

    run = await http.post(f"/orgs/{org_id}/interview-reminders/run", headers=headers)
    assert run.status_code == 200
    assert run.json()["sent"] == []


async def test_only_1h_window_due_not_24h(http: httpx.AsyncClient) -> None:
    headers, org_id = await _staff_context(http, "partial")
    rid = await _requisition(http, headers, org_id)

    # 20 hours out: inside the 24h window but outside the 1h window.
    slot_id = await _book_slot_at(
        http, headers, rid, timedelta(hours=20), "partial-candidate@example.test"
    )

    run = await http.post(f"/orgs/{org_id}/interview-reminders/run", headers=headers)
    assert run.status_code == 200
    sent = run.json()["sent"]
    assert {entry["window"] for entry in sent if entry["slot_id"] == slot_id} == {"24h"}


async def test_cross_org_reminders_denied(http: httpx.AsyncClient) -> None:
    headers_a, org_a = await _staff_context(http, "xa")
    headers_b, _org_b = await _staff_context(http, "xb")
    rid_a = await _requisition(http, headers_a, org_a)
    await _book_slot_at(
        http, headers_a, rid_a, timedelta(minutes=20), "cross-candidate@example.test"
    )

    cross = await http.post(f"/orgs/{org_a}/interview-reminders/run", headers=headers_b)
    assert cross.status_code == 403
