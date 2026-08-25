import os

import httpx
import pymupdf
import pytest
from asgi_lifespan import LifespanManager

from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.environ.get("AIVA_INTEGRATION") != "1",
    reason="integration compose stack not running (set AIVA_INTEGRATION=1)",
)

PASSWORD = "long-enough-password-123"


def _resume_pdf() -> bytes:
    text = (
        "Alex Candidate\n"
        "alex.candidate@example.test | linkedin.com/in/alexcand | +1 (212) 555-0199\n"
        "Backend engineer with 6 years of experience in payments.\n"
        "Skills: Python, PostgreSQL, Docker, Kafka, Kubernetes\n"
    )
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    return doc.tobytes()


@pytest.fixture
async def http() -> httpx.AsyncClient:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _token(http: httpx.AsyncClient) -> str:
    response = await http.post(
        "/auth/login", json={"email": "resume-admin@example.test", "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


async def test_upload_jd_score_roundtrip_with_determinism(http: httpx.AsyncClient) -> None:
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": "Resume Org",
            "admin_email": "resume-admin@example.test",
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201
    token = await _token(http)
    headers = {"Authorization": f"Bearer {token}"}

    dept = await http.post(
        f"/orgs/{org.json()['organization_id']}/departments",
        json={"name": "Platform"},
        headers=headers,
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Senior Backend", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]

    jd = await http.post(
        f"/requisitions/{rid}/job-description",
        json={
            "title": "Senior Backend",
            "raw_text": "Build payment pipelines with Python and Kafka.",
            "required_skills": ["python", "postgresql", "docker"],
            "preferred_skills": ["kafka"],
            "min_years_experience": 5,
        },
        headers=headers,
    )
    assert jd.status_code == 201

    upload = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("alex.pdf", _resume_pdf(), "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    resume_id = upload.json()["id"]
    assert upload.json()["page_count"] >= 1

    detail = await http.get(f"/resumes/{resume_id}", headers=headers)
    assert detail.status_code == 200
    fields = detail.json()["fields"]
    by_name: dict[str, list[dict]] = {}
    for field in fields:
        by_name.setdefault(field["field_name"], []).append(field)
    assert by_name["email"][0]["value"] == "alex.candidate@example.test"
    skills = {field["value"] for field in by_name.get("skill", [])}
    assert {"python", "postgresql", "docker", "kafka"} <= skills

    profile = await http.post(
        f"/requisitions/{rid}/weight-profiles",
        json={
            "name": "default-backend",
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
    pid = profile.json()["id"]

    run_request = {"resume_id": resume_id, "weight_profile_id": pid}
    first = await http.post(f"/requisitions/{rid}/scoring-runs", json=run_request, headers=headers)
    assert first.status_code == 201, first.text
    body_first = first.json()

    for _ in range(2):
        repeat = await http.post(
            f"/requisitions/{rid}/scoring-runs", json=run_request, headers=headers
        )
        assert repeat.status_code == 201
        assert (
            repeat.json()["run_fingerprint"] == body_first["run_fingerprint"]
        ), "determinism violated"
        assert repeat.json()["total_score"] == body_first["total_score"]

    passed_checks = [c for c in body_first["checks"] if c["check"].startswith("required_skill")]
    assert all(c["passed"] for c in passed_checks), body_first["checks"]
    years_check = next(c for c in body_first["checks"] if c["check"] == "min_years_experience")
    assert years_check["passed"]

    technical = next(d for d in body_first["dimensions"] if d["dimension"] == "technical")
    assert technical["evidence_refs"] == ["match_checks"]
    llm_dims = [d for d in body_first["dimensions"] if d["dimension"] != "technical"]
    assert llm_dims and all(d["evidence_refs"] for d in llm_dims)

    runs_list = await http.get(f"/requisitions/{rid}/scoring-runs", headers=headers)
    assert len(runs_list.json()["runs"]) == 3


async def test_duplicate_resume_rejected(http: httpx.AsyncClient) -> None:
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": "Dup Org",
            "admin_email": "dup-admin@example.test",
            "admin_password": PASSWORD,
        },
    )
    token_response = await http.post(
        "/auth/login", json={"email": "dup-admin@example.test", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
    dept = await http.post(
        f"/orgs/{org.json()['organization_id']}/departments", json={"name": "D"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "T", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]
    first = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("a.txt", b"hello world python", "text/plain")},
        headers=headers,
    )
    assert first.status_code == 201
    second = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("a-copy.txt", b"hello world python", "text/plain")},
        headers=headers,
    )
    assert second.status_code == 409


async def test_healthz_alive(http: httpx.AsyncClient) -> None:
    response = await http.get("/healthz")
    assert response.status_code == 200
