import os

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


async def _staff_context(http: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": "Quest Org",
            "admin_email": "quest-admin@example.test",
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    login = await http.post(
        "/auth/login", json={"email": "quest-admin@example.test", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, org.json()[
        "organization_id"
    ]


async def test_questionnaire_lifecycle_with_autosave_and_single_use(
    http: httpx.AsyncClient,
) -> None:
    headers, organization_id = await _staff_context(http)
    dept = await http.post(
        f"/orgs/{organization_id}/departments", json={"name": "People"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Analyst", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]

    created = await http.post(
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
    assert created.status_code == 201, created.text
    qid = created.json()["id"]

    invite = await http.post(
        f"/questionnaires/{qid}/invites",
        json={"candidate_email": "candidate@example.test"},
        headers=headers,
    )
    assert invite.status_code == 201
    token = invite.json()["token"]

    public = await http.get(f"/public/questionnaires/{token}")
    assert public.status_code == 200
    assert len(public.json()["questions"]) == 2

    autosave = await http.put(
        f"/public/questionnaires/{token}/responses",
        json={"answers": {"auth": "yes"}, "submit": False},
    )
    assert autosave.status_code == 200
    assert autosave.json()["missing_required"] == ["notice"]

    reopened = await http.get(f"/public/questionnaires/{token}")
    assert reopened.json()["answers"] == {"auth": "yes"}

    submit_incomplete = await http.put(
        f"/public/questionnaires/{token}/responses",
        json={"answers": {"auth": "yes"}, "submit": True},
    )
    assert submit_incomplete.status_code == 400

    submit_ok = await http.put(
        f"/public/questionnaires/{token}/responses",
        json={"answers": {"auth": "yes", "notice": "30 days"}, "submit": True},
    )
    assert submit_ok.status_code == 200
    assert submit_ok.json()["submitted"] is True
    assert submit_ok.json()["history_entries"] >= 3

    replay = await http.get(f"/public/questionnaires/{token}")
    assert replay.status_code == 409

    resubmit = await http.put(
        f"/public/questionnaires/{token}/responses",
        json={"answers": {"auth": "no", "notice": "0"}, "submit": True},
    )
    assert resubmit.status_code == 409

    staff_list = await http.get(f"/requisitions/{rid}/questionnaire-responses", headers=headers)
    responses = staff_list.json()["responses"]
    assert len(responses) == 1
    assert responses[0]["submitted"] is True


async def test_invalid_questionnaire_rejected(http: httpx.AsyncClient) -> None:
    headers, organization_id = await _staff_context(http)
    dept = await http.post(
        f"/orgs/{organization_id}/departments", json={"name": "Q"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "T2", "department_id": dept.json()["id"]},
        headers=headers,
    )
    bad = await http.post(
        f"/requisitions/{req.json()['id']}/questionnaires",
        json={"title": "Bad", "questions": [{"id": "x", "type": "telepathy", "prompt": "?"}]},
        headers=headers,
    )
    assert bad.status_code == 400


async def test_healthz_alive(http: httpx.AsyncClient) -> None:
    response = await http.get("/healthz")
    assert response.status_code == 200
