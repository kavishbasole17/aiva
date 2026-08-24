import os

import httpx
import pytest

requires_live_stack = pytest.mark.skipif(
    os.environ.get("AIVA_INTEGRATION") != "1",
    reason="integration compose stack not running (set AIVA_INTEGRATION=1)",
)


@requires_live_stack
async def test_readyz_reports_all_dependencies_up(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"postgres": "up", "redis": "up", "minio": "up"}


@requires_live_stack
async def test_healthz_alive(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
