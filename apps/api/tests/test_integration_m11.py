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
CANDIDATE_EMAIL = "jane.candidate@example.test"


@pytest.fixture
async def http() -> httpx.AsyncClient:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def _minimal_pdf() -> bytes:
    lines = ["Jane Candidate", CANDIDATE_EMAIL, "Skills: python, sql", "5 years experience."]
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


async def _bootstrap(http: httpx.AsyncClient) -> tuple[dict[str, str], str, str, str, str]:
    """Returns (admin headers, organization_id, requisition_id, resume_id, department_id)."""
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"m11-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"M11 Org {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    organization_id = org.json()["organization_id"]

    dept = await http.post(
        f"/orgs/{organization_id}/departments", json={"name": "Eng"}, headers=headers
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
    return headers, organization_id, rid, upload.json()["id"], dept.json()["id"]


async def test_dashboard_reflects_created_data(http: httpx.AsyncClient) -> None:
    headers, organization_id, _rid, _resume_id, _dept_id = await _bootstrap(http)
    dashboard = await http.get(f"/orgs/{organization_id}/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["requisitions"]["total"] >= 1
    assert body["resumes"]["total"] >= 1


async def test_blind_screening_redacts_pii(http: httpx.AsyncClient) -> None:
    headers, _org, rid, resume_id, _dept_id = await _bootstrap(http)

    normal = await http.get(f"/resumes/{resume_id}", headers=headers)
    assert normal.status_code == 200
    assert normal.json()["candidate_email"] == CANDIDATE_EMAIL

    blind = await http.get(f"/resumes/{resume_id}?blind=true", headers=headers)
    assert blind.status_code == 200
    body = blind.json()
    assert body["blind"] is True
    assert body["candidate_email"] != CANDIDATE_EMAIL
    email_fields = [f for f in body["fields"] if f["field_name"] == "email"]
    assert email_fields and all("hidden" in f["value"] for f in email_fields)
    skill_fields = [f for f in body["fields"] if f["field_name"] == "skill"]
    assert skill_fields and all(f["value"] != "hidden" for f in skill_fields)

    candidates = await http.get(f"/requisitions/{rid}/candidates?blind=true", headers=headers)
    assert candidates.status_code == 200
    assert all(c["candidate_email"] is None for c in candidates.json()["candidates"])


async def test_scoring_audit_flags_verdict_drift(http: httpx.AsyncClient) -> None:
    headers, _org, rid, resume_id, _dept_id = await _bootstrap(http)
    profile = await http.post(
        f"/requisitions/{rid}/weight-profiles",
        json={
            "name": "default",
            "weights": {
                "technical": 30,
                "experience": 20,
                "domain": 15,
                "education": 10,
                "certifications": 10,
                "soft_skills": 10,
                "stability": 5,
            },
        },
        headers=headers,
    )
    assert profile.status_code == 201, profile.text
    run = await http.post(
        f"/requisitions/{rid}/scoring-runs",
        json={"resume_id": resume_id, "weight_profile_id": profile.json()["id"]},
        headers=headers,
    )
    assert run.status_code == 201, run.text

    audit = await http.get(f"/requisitions/{rid}/scoring-audit", headers=headers)
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["runs_analyzed"] == 1
    # A single deterministic run against one profile should never be flagged.
    assert body["findings"] == []


async def test_questionnaire_clone_kit(http: httpx.AsyncClient) -> None:
    headers, _org, rid, _resume_id, dept_id = await _bootstrap(http)
    other_req = await http.post(
        f"/departments/{dept_id}/requisitions",
        json={"title": "Backend Engineer II", "department_id": dept_id},
        headers=headers,
    )
    target_rid = other_req.json()["id"]

    created = await http.post(
        f"/requisitions/{rid}/questionnaires",
        json={
            "title": "Screening",
            "questions": [
                {"id": "auth", "type": "yes_no", "prompt": "Authorized to work?", "required": True}
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    cloned = await http.post(
        f"/questionnaires/{created.json()['id']}/clone",
        json={"target_requisition_id": target_rid},
        headers=headers,
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["question_count"] == 1
    assert cloned.json()["requisition_id"] == target_rid


async def test_dsar_export_and_erase(http: httpx.AsyncClient) -> None:
    headers, _org, _rid, resume_id, _dept_id = await _bootstrap(http)

    export = await http.post("/dsar/export", json={"email": CANDIDATE_EMAIL}, headers=headers)
    assert export.status_code == 200, export.text
    body = export.json()
    assert body["record_counts"]["resumes"] == 1
    assert body["resumes"][0]["candidate_email"] == CANDIDATE_EMAIL

    erase = await http.post(
        "/dsar/erase", json={"email": CANDIDATE_EMAIL, "confirm": True}, headers=headers
    )
    assert erase.status_code == 200, erase.text
    assert erase.json()["erased"] is True

    after = await http.get(f"/resumes/{resume_id}", headers=headers)
    assert after.status_code == 200
    after_body = after.json()
    assert after_body["candidate_email"] is None
    # A security review of this endpoint caught that the first cut redacted
    # candidate_email/full_text but left filename and the PII fields'
    # source_quote untouched on the very same rows — both must be gone too.
    assert "redacted" in after_body["filename"].lower()
    for field in after_body["fields"]:
        if field["field_name"] in {"email", "phone", "name", "full_name", "linkedin"}:
            assert CANDIDATE_EMAIL not in field["source_quote"]
            assert "redacted" in field["source_quote"].lower()

    second_export = await http.post(
        "/dsar/export", json={"email": CANDIDATE_EMAIL}, headers=headers
    )
    assert second_export.status_code == 404


async def test_dsar_requires_admin_role(http: httpx.AsyncClient) -> None:
    headers, org, _rid, _resume_id, _dept_id = await _bootstrap(http)
    # Create a non-admin staff user and confirm they're rejected.
    recruiter_email = f"recruiter-{uuid.uuid4().hex[:8]}@example.test"
    created = await http.post(
        f"/orgs/{org}/users",
        json={"email": recruiter_email, "password": PASSWORD, "role": "recruiter"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    login = await http.post("/auth/login", json={"email": recruiter_email, "password": PASSWORD})
    recruiter_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = await http.post(
        "/dsar/export", json={"email": CANDIDATE_EMAIL}, headers=recruiter_headers
    )
    assert denied.status_code == 403


async def test_integrity_signal_round_trip(http: httpx.AsyncClient) -> None:
    headers, _org, rid, resume_id, _dept_id = await _bootstrap(http)
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
    await http.post(
        f"/slots/{slots[0]['id']}/book", json={"candidate_email": CANDIDATE_EMAIL}, headers=headers
    )
    session = await http.post(
        f"/slots/{slots[0]['id']}/interview-session",
        json={"resume_id": resume_id},
        headers=headers,
    )
    assert session.status_code == 201, session.text
    token = session.json()["token"]
    session_id = session.json()["id"]

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

    reported = await http.post(
        f"/public/interview-sessions/{token}/integrity-signals",
        json={"signal_type": "tab_blur", "detail": {}},
    )
    assert reported.status_code == 201, reported.text

    listed = await http.get(f"/interview-sessions/{session_id}/integrity-signals", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["summary"] == {"tab_blur": 1}

    rejected = await http.post(
        f"/public/interview-sessions/{token}/integrity-signals",
        json={"signal_type": "not_a_real_signal", "detail": {}},
    )
    assert rejected.status_code == 400
