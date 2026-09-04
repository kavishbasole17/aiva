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


async def _staff_context(http: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"quest-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Quest Org {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
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
    # Two history entries: the autosave and the successful submit. The rejected
    # incomplete-submission attempt correctly rolls back and leaves no trace.
    assert submit_ok.json()["history_entries"] == 2

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


async def test_ai_evaluation_of_submitted_response(http: httpx.AsyncClient) -> None:
    """Explicitly scoped out of Milestone 6 pending a real AI model
    (docs/PLAN.md's own note); unblocked by ADR-024, delivered by ADR-033.
    Proves the full round trip against the real (containerized) AI gateway,
    not just that the endpoint exists."""
    headers, organization_id = await _staff_context(http)
    dept = await http.post(
        f"/orgs/{organization_id}/departments", json={"name": "Eval"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Backend Engineer", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]

    created = await http.post(
        f"/requisitions/{rid}/questionnaires",
        json={
            "title": "Screening",
            "questions": [
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
    qid = created.json()["id"]

    invite = await http.post(
        f"/questionnaires/{qid}/invites",
        json={"candidate_email": "eval-candidate@example.test"},
        headers=headers,
    )
    token = invite.json()["token"]

    # Evaluating before submission is rejected, not silently evaluated on
    # incomplete data.
    responses_before = await http.get(
        f"/requisitions/{rid}/questionnaire-responses", headers=headers
    )
    assert responses_before.json()["responses"] == []

    submit = await http.put(
        f"/public/questionnaires/{token}/responses",
        json={"answers": {"notice": "2 weeks"}, "submit": True},
    )
    assert submit.status_code == 200, submit.text

    responses = await http.get(f"/requisitions/{rid}/questionnaire-responses", headers=headers)
    response_row = responses.json()["responses"][0]
    assert response_row["ai_evaluation"] is None
    response_id = response_row["id"]

    evaluation = await http.post(
        f"/questionnaire-responses/{response_id}/evaluate", headers=headers
    )
    assert evaluation.status_code == 200, evaluation.text
    body = evaluation.json()
    assert body["recommendation"] in {"proceed", "hold", "reject"}
    assert 0 <= body["overall_score"] <= 100
    assert isinstance(body["inconsistencies"], list)
    assert isinstance(body["missing_critical_info"], list)

    # Persisted: a fresh GET now shows the evaluation without re-running it.
    responses_after = await http.get(
        f"/requisitions/{rid}/questionnaire-responses", headers=headers
    )
    assert responses_after.json()["responses"][0]["ai_evaluation"] == body


async def test_evaluation_rejected_before_submission(http: httpx.AsyncClient) -> None:
    headers, organization_id = await _staff_context(http)
    dept = await http.post(
        f"/orgs/{organization_id}/departments", json={"name": "Eval2"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Role", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]
    created = await http.post(
        f"/requisitions/{rid}/questionnaires",
        json={
            "title": "Screening",
            "questions": [
                {"id": "notice", "type": "short_text", "prompt": "Notice period?"},
            ],
        },
        headers=headers,
    )
    qid = created.json()["id"]
    invite = await http.post(
        f"/questionnaires/{qid}/invites",
        json={"candidate_email": "unfinished@example.test"},
        headers=headers,
    )
    token = invite.json()["token"]
    await http.put(
        f"/public/questionnaires/{token}/responses",
        json={"answers": {}, "submit": False},
    )
    responses = await http.get(f"/requisitions/{rid}/questionnaire-responses", headers=headers)
    response_id = responses.json()["responses"][0]["id"]

    evaluation = await http.post(
        f"/questionnaire-responses/{response_id}/evaluate", headers=headers
    )
    assert evaluation.status_code == 409
