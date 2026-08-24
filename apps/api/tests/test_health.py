import httpx
import pytest


async def test_healthz_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unknown_route_returns_404_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [("/healthz", 200), ("/readyz", 503)],
)
async def test_offline_readiness_is_honest(
    client: httpx.AsyncClient,
    path: str,
    expected_status: int,
) -> None:
    response = await client.get(path)
    assert response.status_code == expected_status
    if path == "/readyz":
        body = response.json()
        assert body["status"] == "degraded"
        assert set(body["checks"]) == {"postgres", "redis", "minio"}
        assert all(value == "down" for value in body["checks"].values())
