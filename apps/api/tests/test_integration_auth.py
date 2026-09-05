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

ORG_A = "Org A Matrix"
ORG_B = "Org B Matrix"
ADMIN_EMAIL = "admin-a@example.test"
STAFF_PASSWORD = "long-enough-password-123"


class Client:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        self.token: str | None = None

    def auth_headers(self) -> dict[str, str]:
        if self.token is None:
            return {}
        return {"Authorization": f"Bearer {self.token}"}


async def register_org(http: httpx.AsyncClient, name: str, email: str) -> dict:
    response = await http.post(
        "/auth/register-org",
        json={"organization_name": name, "admin_email": email, "admin_password": STAFF_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(http: httpx.AsyncClient, email: str) -> str:
    response = await http.post("/auth/login", json={"email": email, "password": STAFF_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
async def http() -> httpx.AsyncClient:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _bootstrap_world(http: httpx.AsyncClient) -> dict:
    org_a = await register_org(http, ORG_A, ADMIN_EMAIL)
    org_b = await register_org(http, ORG_B, "admin-b@example.test")

    admin_a_token = await login(http, ADMIN_EMAIL)

    staff_response = await http.post(
        f"/orgs/{org_a['organization_id']}/users",
        json={
            "email": "recruiter-a@example.test",
            "password": STAFF_PASSWORD,
            "role": "recruiter",
        },
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert staff_response.status_code == 201, staff_response.text

    dept_response = await http.post(
        f"/orgs/{org_a['organization_id']}/departments",
        json={"name": "Engineering"},
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert dept_response.status_code == 201, dept_response.text

    req_response = await http.post(
        f"/departments/{dept_response.json()['id']}/requisitions",
        json={"title": "Senior Backend Engineer", "department_id": dept_response.json()["id"]},
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert req_response.status_code == 201, req_response.text

    return {
        "org_a": org_a,
        "org_b": org_b,
        "department_id": dept_response.json()["id"],
        "requisition_id": req_response.json()["id"],
        "admin_a_token": admin_a_token,
    }


async def test_full_authorization_matrix(http: httpx.AsyncClient) -> None:
    world = await _bootstrap_world(http)

    recruiter_token = await login(http, "recruiter-a@example.test")
    admin_b_token = await login(http, "admin-b@example.test")

    cases = [
        ("GET", "/me", {}, 200),
        (
            "POST",
            "/auth/register-org",
            {
                "organization_name": "Xco",
                "admin_email": "x@x.test",
                "admin_password": STAFF_PASSWORD,
            },
            201,
        ),
        (
            "POST",
            f"/orgs/{world['org_a']['organization_id']}/users",
            {"email": "new@x.test", "password": STAFF_PASSWORD, "role": "interviewer"},
            403,
        ),
        ("POST", f"/orgs/{world['org_a']['organization_id']}/departments", {"name": "Sales"}, 403),
        (
            "POST",
            f"/departments/{world['department_id']}/requisitions",
            {"title": "T", "department_id": world["department_id"]},
            201,
        ),
        ("GET", f"/requisitions/{world['requisition_id']}", {}, 200),
        ("PATCH", f"/requisitions/{world['requisition_id']}", {"status": "open"}, 200),
        ("DELETE", f"/requisitions/{world['requisition_id']}", None, 403),
        ("GET", "/audit-events", None, 403),
    ]

    for method, path, body, expected in cases:
        response = await http.request(
            method,
            path,
            json=body,
            headers={"Authorization": f"Bearer {recruiter_token}"},
        )
        assert (
            response.status_code == expected
        ), f"{method} {path}: got {response.status_code}, want {expected}"

    cross_response = await http.get(
        f"/requisitions/{world['requisition_id']}",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_response.status_code == 404

    admin_cases = [
        ("DELETE", f"/requisitions/{world['requisition_id']}", None, 204),
        ("GET", "/audit-events", None, 200),
    ]
    for method, path, body, expected in admin_cases:
        response = await http.request(
            method, path, json=body, headers={"Authorization": f"Bearer {world['admin_a_token']}"}
        )
        assert response.status_code == expected, f"{method} {path}: got {response.status_code}"


async def test_refresh_rotation_reuse_revokes_family(http: httpx.AsyncClient) -> None:
    await register_org(http, "Rotation Org", "rotation-admin@example.test")
    login_response = await http.post(
        "/auth/login",
        json={"email": "rotation-admin@example.test", "password": STAFF_PASSWORD},
    )
    first_refresh = login_response.json()["refresh_token"]

    second = await http.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert second.status_code == 200
    new_refresh = second.json()["refresh_token"]

    replay = await http.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401

    third = await http.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert third.status_code == 401


async def test_audit_chain_verifies_intact(http: httpx.AsyncClient) -> None:
    await register_org(http, "Audit Org", "audit-admin@example.test")
    token = await login(http, "audit-admin@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    events = await http.get("/audit-events", headers=headers)
    assert events.status_code == 200
    event_count = len(events.json()["events"])
    assert event_count >= 1
    verification = await http.get("/audit-events/verify", headers=headers)
    assert verification.status_code == 200
    assert verification.json() == {"intact": True, "event_count": event_count}


async def test_mfa_flow(http: httpx.AsyncClient) -> None:
    import pyotp

    await register_org(http, "Mfa Org", "mfa-admin@example.test")
    token = await login(http, "mfa-admin@example.test")
    headers = {"Authorization": f"Bearer {token}"}

    enroll = await http.post("/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    activate = await http.post(
        "/auth/mfa/activate", json={"code": pyotp.TOTP(secret).now()}, headers=headers
    )
    assert activate.status_code == 200

    password_only = await http.post(
        "/auth/login", json={"email": "mfa-admin@example.test", "password": STAFF_PASSWORD}
    )
    assert password_only.status_code == 401

    bad_code = await http.post(
        "/auth/login",
        json={"email": "mfa-admin@example.test", "password": STAFF_PASSWORD, "totp_code": "000000"},
    )
    assert bad_code.status_code == 401

    good_login = await http.post(
        "/auth/login",
        json={
            "email": "mfa-admin@example.test",
            "password": STAFF_PASSWORD,
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert good_login.status_code == 200


async def test_healthz_alive(http: httpx.AsyncClient) -> None:
    response = await http.get("/healthz")
    assert response.status_code == 200


async def test_login_rate_limits_failed_attempts(http: httpx.AsyncClient) -> None:
    # M12 pen-test finding: /auth/login previously had no limit on failed
    # attempts at all. Exhausts the default per-account failure budget (10)
    # with wrong passwords, then proves the account is genuinely paused --
    # not just "guessing is hard" -- by showing even the correct password is
    # rejected while locked out.
    suffix = uuid.uuid4().hex[:8]
    email = f"lockout-{suffix}@example.test"
    await register_org(http, f"Lockout Org {suffix}", email)

    for _ in range(10):
        wrong = await http.post("/auth/login", json={"email": email, "password": "wrong-password"})
        assert wrong.status_code == 401

    still_wrong = await http.post(
        "/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert still_wrong.status_code == 429

    correct_but_locked = await http.post(
        "/auth/login", json={"email": email, "password": STAFF_PASSWORD}
    )
    assert correct_but_locked.status_code == 429
