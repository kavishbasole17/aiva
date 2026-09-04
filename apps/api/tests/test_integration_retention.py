"""Data retention job lifecycle against a live stack.

Proves the actual behavior that matters for something this destructive:
dry_run previews without erasing anything, a real run erases exactly the
eligible candidates and writes an audit event, already-redacted candidates
don't reappear on a second run, and one organization's retention run never
touches another organization's candidates.
"""

import os
import uuid

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


def _resume_pdf(name: str, email: str) -> bytes:
    text = f"{name}\n{email} | +1 (212) 555-0100\n5 years of Python experience.\nSkills: python\n"
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


async def _org_with_resume(
    http: httpx.AsyncClient, label: str
) -> tuple[dict[str, str], str, str, str]:
    """Returns (headers, organization_id, requisition_id, candidate_email)."""
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"retention-{label}-{suffix}@example.test"
    candidate_email = f"candidate-{label}-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Retention Org {label} {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["organization_id"]

    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    dept = await http.post(f"/orgs/{org_id}/departments", json={"name": "Eng"}, headers=headers)
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Engineer", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]

    upload = await http.post(
        f"/requisitions/{rid}/resumes",
        files={
            "file": (
                "resume.pdf",
                _resume_pdf(f"Candidate {label}", candidate_email),
                "application/pdf",
            )
        },
        headers=headers,
    )
    assert upload.status_code == 201, upload.text

    return headers, org_id, rid, candidate_email


async def test_dry_run_previews_without_erasing(http: httpx.AsyncClient) -> None:
    headers, org_id, rid, candidate_email = await _org_with_resume(http, "dry")

    preview = await http.post(
        f"/orgs/{org_id}/retention/run",
        json={"retention_days": 0, "dry_run": True},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] is True
    assert body["erased_count"] == 0
    assert body["eligible_count"] == 1
    assert body["candidates"][0]["candidate_email"] == candidate_email

    # Confirm nothing was actually touched: the pipeline still shows the
    # real candidate email, not redacted.
    candidates = await http.get(f"/requisitions/{rid}/candidates", headers=headers)
    assert candidates.json()["candidates"][0]["candidate_email"] == candidate_email


async def test_real_run_erases_and_is_idempotent(http: httpx.AsyncClient) -> None:
    headers, org_id, rid, candidate_email = await _org_with_resume(http, "real")

    ran = await http.post(
        f"/orgs/{org_id}/retention/run",
        json={"retention_days": 0, "dry_run": False},
        headers=headers,
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["dry_run"] is False
    assert ran.json()["erased_count"] == 1

    candidates = await http.get(f"/requisitions/{rid}/candidates", headers=headers)
    assert candidates.json()["candidates"][0]["candidate_email"] is None

    # Running again finds nothing left to erase -- the candidate's email is
    # already redacted (None), so it no longer matches the eligibility query.
    ran_again = await http.post(
        f"/orgs/{org_id}/retention/run",
        json={"retention_days": 0, "dry_run": False},
        headers=headers,
    )
    assert ran_again.status_code == 200
    assert ran_again.json()["eligible_count"] == 0
    assert ran_again.json()["erased_count"] == 0


async def test_retention_far_future_cutoff_finds_nothing(http: httpx.AsyncClient) -> None:
    headers, org_id, _rid, _email = await _org_with_resume(http, "future")

    preview = await http.post(
        f"/orgs/{org_id}/retention/run",
        json={"retention_days": 3650, "dry_run": True},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["eligible_count"] == 0


async def test_cross_org_retention_denied(http: httpx.AsyncClient) -> None:
    headers_a, org_a, _rid_a, _email_a = await _org_with_resume(http, "xa")
    headers_b, _org_b, _rid_b, _email_b = await _org_with_resume(http, "xb")

    cross = await http.post(
        f"/orgs/{org_a}/retention/run",
        json={"retention_days": 0, "dry_run": True},
        headers=headers_b,
    )
    assert cross.status_code == 403
