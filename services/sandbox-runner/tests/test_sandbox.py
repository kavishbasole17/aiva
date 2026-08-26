import httpx


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200


async def test_runtimes_lists_languages(client: httpx.AsyncClient) -> None:
    response = await client.get("/runtimes")
    assert response.status_code == 200
    body = response.json()
    assert "python" in body["languages"]
    assert "javascript" in body["languages"]


async def test_execute_python_success(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/execute", json={"language": "python", "source": "print(1 + 1)"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stdout"].strip() == "2"
    assert body["exit_code"] == 0
    assert body["timed_out"] is False


async def test_execute_unsupported_language_400(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/execute", json={"language": "ruby", "source": "puts 1"})
    assert response.status_code == 400


async def test_execute_source_too_large_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/execute", json={"language": "python", "source": "x = 1\n" * 100_000}
    )
    assert response.status_code == 400


async def test_execute_empty_source_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/execute", json={"language": "python", "source": ""})
    assert response.status_code == 422
