import httpx

from app.security_headers import CSP_POLICY


async def test_csp_matches_spec_exactly(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers["content-security-policy"] == CSP_POLICY


async def test_secondary_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_security_headers_on_error_responses(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-security-policy"] == CSP_POLICY
