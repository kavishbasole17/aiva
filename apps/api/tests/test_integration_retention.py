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


def _minimal_pdf(candidate_email: str) -> bytes:
    lines = ["Jane Candidate", candidate_email, "Skills: python, sql", "5 years experience."]
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


async def _bootstrap(http: httpx.AsyncClient) -> tuple[dict[str, str], str, str]:
    """Registers a fresh org + admin, uploads one resume.

    Returns (admin headers, organization id, requisition id).
    """
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"retention-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Retention Org {suffix}",
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
    return headers, organization_id, req.json()["id"]


async def _upload_resume(
    http: httpx.AsyncClient, headers: dict[str, str], rid: str, email: str
) -> str:
    upload = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("resume.pdf", _minimal_pdf(email), "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    return str(upload.json()["id"])


async def test_retention_sweep_erases_stale_candidates(http: httpx.AsyncClient) -> None:
    headers, _org, rid = await _bootstrap(http)
    email = f"stale-{uuid.uuid4().hex[:8]}@example.test"
    resume_id = await _upload_resume(http, headers, rid, email)

    # retention_days=0 means "anything not created in this exact instant is
    # stale" -- the resume was created moments ago, so it's swept immediately
    # without waiting for a real retention window to elapse.
    swept = await http.post("/retention/run", json={"retention_days": 0}, headers=headers)
    assert swept.status_code == 200, swept.text
    body = swept.json()
    assert body["candidates_erased"] == 1
    assert body["record_counts"]["resumes"] == 1
    assert len(body["candidate_email_sha256s"]) == 1

    after = await http.get(f"/resumes/{resume_id}", headers=headers)
    assert after.status_code == 200
    after_body = after.json()
    assert after_body["candidate_email"] is None
    assert "redacted" in after_body["filename"].lower()


async def test_retention_sweep_exempts_recent_candidates_under_the_default_window(
    http: httpx.AsyncClient,
) -> None:
    headers, _org, rid = await _bootstrap(http)
    email = f"fresh-{uuid.uuid4().hex[:8]}@example.test"
    resume_id = await _upload_resume(http, headers, rid, email)

    # No override -> falls back to AIVA_RETENTION_DAYS (default 730 days).
    # A resume created seconds ago is nowhere near stale.
    swept = await http.post("/retention/run", json={}, headers=headers)
    assert swept.status_code == 200, swept.text
    assert swept.json()["candidates_erased"] == 0

    after = await http.get(f"/resumes/{resume_id}", headers=headers)
    assert after.status_code == 200
    assert after.json()["candidate_email"] == email


async def test_retention_sweep_requires_admin_role(http: httpx.AsyncClient) -> None:
    headers, org, _rid = await _bootstrap(http)
    recruiter_email = f"recruiter-{uuid.uuid4().hex[:8]}@example.test"
    created = await http.post(
        f"/orgs/{org}/users",
        json={"email": recruiter_email, "password": PASSWORD, "role": "recruiter"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    login = await http.post("/auth/login", json={"email": recruiter_email, "password": PASSWORD})
    recruiter_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = await http.post("/retention/run", json={}, headers=recruiter_headers)
    assert denied.status_code == 403
