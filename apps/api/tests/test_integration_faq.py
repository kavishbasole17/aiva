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


def _minimal_pdf() -> bytes:
    lines = ["Jane Candidate", "jane.candidate@example.test", "Skills: python, sql"]
    content = (
        "BT /F1 12 Tf 40 750 Td 14 TL\n" + "\n".join(f"({line}) Tj T*" for line in lines) + "\nET"
    )
    stream = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    return bytes(out)


async def _active_session(http: httpx.AsyncClient) -> tuple[dict[str, str], str, str]:
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"faq-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Faq Org {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    dept = await http.post(
        f"/orgs/{org.json()['organization_id']}/departments", json={"name": "Eng"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Backend Engineer", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]
    jd = await http.post(
        f"/requisitions/{rid}/job-description",
        json={
            "title": "Backend Engineer",
            "raw_text": "Build services in python.",
            "required_skills": ["python"],
            "preferred_skills": [],
            "min_years_experience": 1,
        },
        headers=headers,
    )
    assert jd.status_code == 201, jd.text
    upload = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("resume.pdf", _minimal_pdf(), "application/pdf")},
        data={},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text

    slot_gen = await http.post(
        f"/requisitions/{rid}/slots/generate",
        json={
            "date_from": "2026-09-01",
            "date_to": "2026-09-02",
            "timezone_name": "UTC",
            "local_start": "10:00",
            "local_end": "12:00",
            "duration_minutes": 45,
            "buffer_minutes": 0,
        },
        headers=headers,
    )
    assert slot_gen.status_code == 201, slot_gen.text
    slots = (await http.get(f"/requisitions/{rid}/slots", headers=headers)).json()["slots"]
    booked = await http.post(
        f"/slots/{slots[0]['id']}/book",
        json={"candidate_email": "jane.candidate@example.test"},
        headers=headers,
    )
    assert booked.status_code == 200, booked.text
    created = await http.post(
        f"/slots/{slots[0]['id']}/interview-session", json={}, headers=headers
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]

    state = await http.get(f"/public/interview-sessions/{token}")
    consent_version = state.json()["consent"]["version"]
    await http.post(
        f"/public/interview-sessions/{token}/consent",
        json={"accepted_version": consent_version, "granted": True},
    )
    passing_report = {
        "suite_version": state.json()["precheck"]["suite_version"],
        "devices": [
            {"kind": "camera", "status": "ok"},
            {"kind": "microphone", "status": "ok"},
            {"kind": "speaker", "status": "ok"},
        ],
        "connection": "good",
        "bandwidth_kbps": 1500,
        "browser": "pytest-agent",
    }
    await http.post(f"/public/interview-sessions/{token}/precheck", json=passing_report)
    started = await http.post(f"/public/interview-sessions/{token}/start")
    assert started.status_code == 200, started.text

    return headers, rid, token


async def test_faq_rag_round_trip(http: httpx.AsyncClient) -> None:
    headers, rid, token = await _active_session(http)

    created = await http.post(
        f"/requisitions/{rid}/faq",
        json={
            "title": "Interview format",
            "body": "The technical interview is 45 minutes: one live coding "
            "exercise and a short system-design discussion.",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    second = await http.post(
        f"/requisitions/{rid}/faq",
        json={"title": "Compensation range", "body": "The band for this role is $140k-$180k base."},
        headers=headers,
    )
    assert second.status_code == 201, second.text

    listed = await http.get(f"/requisitions/{rid}/faq", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["documents"]) == 2

    asked = await http.post(
        f"/public/interview-sessions/{token}/faq",
        json={"question": "How long is the technical interview?"},
    )
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["answer"]
    assert len(body["retrieved"]) > 0
    assert 0.0 <= body["confidence"] <= 1.0


async def test_faq_ask_with_no_documents_returns_graceful_fallback(
    http: httpx.AsyncClient,
) -> None:
    _headers, _rid, token = await _active_session(http)
    asked = await http.post(
        f"/public/interview-sessions/{token}/faq",
        json={"question": "Anything at all?"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["retrieved"] == []


async def test_faq_create_requires_staff_role(http: httpx.AsyncClient) -> None:
    _headers, rid, _token = await _active_session(http)
    unauthenticated = await http.post(f"/requisitions/{rid}/faq", json={"title": "x", "body": "y"})
    assert unauthenticated.status_code == 401
