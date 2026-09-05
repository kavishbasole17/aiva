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

# Kept in its own file/process, deliberately: slowapi's Limiter (app/rate_limit.py)
# is a process-wide in-memory singleton, so a test that deliberately exhausts
# AUTH_LOGIN_LIMIT ("10/minute") would otherwise poison every other test in the
# same pytest process that also needs to log in. Each integration test file
# already runs as its own `pytest` invocation in CI, giving this a clean budget.


@pytest.fixture
async def http() -> httpx.AsyncClient:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_login_endpoint_is_rate_limited(http: httpx.AsyncClient) -> None:
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": "Rate Limit Org",
            "admin_email": "rate-limit-admin@example.test",
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text

    # AUTH_LOGIN_LIMIT is "10/minute" -- this is the first login-endpoint
    # traffic in this process, so all 10 slots are available. Wrong password
    # on purpose: the limiter counts every request, but a real attacker would
    # be guessing, not logging in successfully every time.
    for _ in range(10):
        attempt = await http.post(
            "/auth/login",
            json={"email": "rate-limit-admin@example.test", "password": "wrong-password"},
        )
        assert attempt.status_code == 401

    limited = await http.post(
        "/auth/login",
        json={"email": "rate-limit-admin@example.test", "password": "wrong-password"},
    )
    assert limited.status_code == 429

    # Still limited even with the correct password -- this pauses the
    # endpoint itself for the window, not just failed guesses.
    still_limited = await http.post(
        "/auth/login",
        json={"email": "rate-limit-admin@example.test", "password": PASSWORD},
    )
    assert still_limited.status_code == 429
