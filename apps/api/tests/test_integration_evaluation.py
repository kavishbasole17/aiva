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


async def _full_candidate_signal(http: httpx.AsyncClient) -> tuple[dict[str, str], str, str]:
    """Bootstraps a resume with a scoring run, a partial (unsubmitted)
    questionnaire response, and a completed interview session with one
    passing coding task — every evaluation component has real data.
    Returns (staff headers, requisition_id, resume_id).
    """
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"eval-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Eval Org {suffix}",
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
    resume_id = upload.json()["id"]

    # Resume component: a scoring run.
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

    # Questionnaire component: invited, one of two answered, not submitted.
    questionnaire = await http.post(
        f"/requisitions/{rid}/questionnaires",
        json={
            "title": "Screening",
            "questions": [
                {"id": "auth", "type": "yes_no", "prompt": "Authorized to work?", "required": True},
                {
                    "id": "notice",
                    "type": "short_text",
                    "prompt": "Notice period?",
                    "required": True,
                },
            ],
        },
        headers=headers,
    )
    assert questionnaire.status_code == 201, questionnaire.text
    invite = await http.post(
        f"/questionnaires/{questionnaire.json()['id']}/invites",
        json={"candidate_email": CANDIDATE_EMAIL},
        headers=headers,
    )
    assert invite.status_code == 201, invite.text
    autosave = await http.put(
        f"/public/questionnaires/{invite.json()['token']}/responses",
        json={"answers": {"auth": "yes"}, "submit": False},
    )
    assert autosave.status_code == 200, autosave.text

    # Interview + coding component: full lifecycle to completion.
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
        f"/slots/{slots[0]['id']}/book", json={"candidate_email": CANDIDATE_EMAIL}, headers=headers
    )
    assert booked.status_code == 200, booked.text
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

    task = await http.post(
        f"/interview-sessions/{session_id}/coding-tasks",
        json={
            "title": "Two Sum",
            "prompt": "Return indices summing to target.",
            "starter_code": "",
            "language": "python",
        },
        headers=headers,
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    run_result = await http.post(
        f"/public/interview-sessions/{token}/coding-tasks/{task_id}/run",
        json={"source": "print('ok')"},
    )
    assert run_result.status_code == 200, run_result.text
    assert run_result.json()["exit_code"] == 0

    return headers, rid, resume_id


async def test_generate_and_export_evaluation(http: httpx.AsyncClient) -> None:
    headers, rid, resume_id = await _full_candidate_signal(http)

    generated = await http.post(
        f"/requisitions/{rid}/resumes/{resume_id}/evaluation", headers=headers
    )
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert 0 <= body["overall_score"] <= 100
    assert body["verdict"] in {"auto_reject", "hold", "shortlist", "highly_recommended"}
    component_names = {c["name"] for c in body["components"]}
    assert component_names == {"resume", "questionnaire", "interview", "coding"}
    report_id = body["id"]

    fetched = await http.get(f"/requisitions/{rid}/resumes/{resume_id}/evaluation", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == report_id

    pdf = await http.get(f"/evaluation-reports/{report_id}/export.pdf", headers=headers)
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-type"] == "application/pdf"

    xlsx = await http.get(f"/evaluation-reports/{report_id}/export.xlsx", headers=headers)
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.content[:2] == b"PK"


async def test_evaluation_with_no_signal_returns_409(http: httpx.AsyncClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"eval-empty-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Empty Org {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    dept = await http.post(
        f"/orgs/{org.json()['organization_id']}/departments", json={"name": "Eng"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "T", "department_id": dept.json()["id"]},
        headers=headers,
    )
    upload = await http.post(
        f"/requisitions/{req.json()['id']}/resumes",
        files={"file": ("resume.pdf", _minimal_pdf(), "application/pdf")},
        data={},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    response = await http.post(
        f"/requisitions/{req.json()['id']}/resumes/{upload.json()['id']}/evaluation",
        headers=headers,
    )
    assert response.status_code == 409


async def test_evaluation_report_is_org_isolated(http: httpx.AsyncClient) -> None:
    headers, rid, resume_id = await _full_candidate_signal(http)
    generated = await http.post(
        f"/requisitions/{rid}/resumes/{resume_id}/evaluation", headers=headers
    )
    report_id = generated.json()["id"]

    suffix = uuid.uuid4().hex[:8]
    outsider_email = f"outsider-{suffix}@example.test"
    outsider_org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Outsider {suffix}",
            "admin_email": outsider_email,
            "admin_password": PASSWORD,
        },
    )
    assert outsider_org.status_code == 201
    outsider_login = await http.post(
        "/auth/login", json={"email": outsider_email, "password": PASSWORD}
    )
    outsider_headers = {"Authorization": f"Bearer {outsider_login.json()['access_token']}"}
    leaked = await http.get(f"/evaluation-reports/{report_id}/export.pdf", headers=outsider_headers)
    assert leaked.status_code == 404
