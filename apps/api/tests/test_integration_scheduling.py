"""Scheduling lifecycle against a live stack.

DST-correctness and buffer/blackout arithmetic are unit-tested directly in
test_scheduling.py (pure functions, no I/O needed). This file proves the
HTTP/DB wiring around that logic instead: slot generation persists and is
idempotent on re-generation, listing reflects real state, booking a slot
returns a valid .ics invite and rejects a double-book, and cross-org access
is denied rather than merely hidden -- the gap this repo's own README noted
as still open ("Milestone 7's scheduling integration test").
"""

import os
import uuid

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
    admin_email = f"sched-{label}-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Sched Org {label} {suffix}",
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


GENERATE_BODY = {
    "date_from": "2026-09-07",
    "date_to": "2026-09-08",
    "timezone_name": "UTC",
    "local_start": "09:00:00",
    "local_end": "12:00:00",
    "duration_minutes": 45,
    "buffer_minutes": 10,
    "include_weekends": False,
}


async def test_generate_list_book_lifecycle(http: httpx.AsyncClient) -> None:
    headers, org_id = await _staff_context(http, "gen")
    rid = await _requisition(http, headers, org_id)

    generated = await http.post(
        f"/requisitions/{rid}/slots/generate", json=GENERATE_BODY, headers=headers
    )
    assert generated.status_code == 201, generated.text
    first_batch = generated.json()["created"]
    assert first_batch > 0

    # Re-generating the identical rule must not duplicate already-open slots.
    regenerated = await http.post(
        f"/requisitions/{rid}/slots/generate", json=GENERATE_BODY, headers=headers
    )
    assert regenerated.status_code == 201
    assert regenerated.json()["created"] == 0

    listed = await http.get(f"/requisitions/{rid}/slots", headers=headers)
    assert listed.status_code == 200
    slots = listed.json()["slots"]
    assert len(slots) == first_batch
    assert all(slot["status"] == "open" for slot in slots)

    slot_id = slots[0]["id"]
    booked = await http.post(
        f"/slots/{slot_id}/book",
        json={"candidate_email": "candidate@example.test"},
        headers=headers,
    )
    assert booked.status_code == 200, booked.text
    body = booked.json()
    assert body["status"] == "booked"
    assert "BEGIN:VCALENDAR" in body["ics"]
    assert "candidate@example.test" in body["ics"]

    # Booking an already-booked slot is rejected, not silently overwritten.
    double_book = await http.post(
        f"/slots/{slot_id}/book",
        json={"candidate_email": "someone-else@example.test"},
        headers=headers,
    )
    assert double_book.status_code == 409

    after = await http.get(f"/requisitions/{rid}/slots", headers=headers)
    booked_slot = next(slot for slot in after.json()["slots"] if slot["id"] == slot_id)
    assert booked_slot["status"] == "booked"
    assert booked_slot["booked_for_email"] == "candidate@example.test"


async def test_cross_org_scheduling_access_denied(http: httpx.AsyncClient) -> None:
    headers_a, org_a = await _staff_context(http, "a")
    headers_b, _org_b = await _staff_context(http, "b")
    rid_a = await _requisition(http, headers_a, org_a)

    generated = await http.post(
        f"/requisitions/{rid_a}/slots/generate", json=GENERATE_BODY, headers=headers_a
    )
    assert generated.status_code == 201

    # Org B cannot generate, list, or book against org A's requisition/slots.
    cross_generate = await http.post(
        f"/requisitions/{rid_a}/slots/generate", json=GENERATE_BODY, headers=headers_b
    )
    assert cross_generate.status_code == 404

    cross_list = await http.get(f"/requisitions/{rid_a}/slots", headers=headers_b)
    assert cross_list.status_code == 404

    own_slots = await http.get(f"/requisitions/{rid_a}/slots", headers=headers_a)
    slot_id = own_slots.json()["slots"][0]["id"]

    cross_book = await http.post(
        f"/slots/{slot_id}/book",
        json={"candidate_email": "candidate@example.test"},
        headers=headers_b,
    )
    assert cross_book.status_code == 404


async def test_healthz_alive(http: httpx.AsyncClient) -> None:
    response = await http.get("/healthz")
    assert response.status_code == 200
