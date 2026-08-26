import math

import httpx

from app.embeddings import EMBEDDING_DIM, MockEmbedder


async def test_mock_embedder_is_deterministic() -> None:
    embedder = MockEmbedder()
    first = await embedder.embed("what is the interview format?")
    second = await embedder.embed("what is the interview format?")
    assert first.vector == second.vector


async def test_mock_embedder_differs_by_input() -> None:
    embedder = MockEmbedder()
    a = await embedder.embed("question one")
    b = await embedder.embed("question two")
    assert a.vector != b.vector


async def test_mock_embedder_is_unit_length_and_right_shape() -> None:
    embedder = MockEmbedder()
    result = await embedder.embed("normalize me")
    assert result.dim == EMBEDDING_DIM
    assert len(result.vector) == EMBEDDING_DIM
    norm = math.sqrt(sum(component * component for component in result.vector))
    assert abs(norm - 1.0) < 1e-6


async def test_embed_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/embed", json={"text": "when do I hear back?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dim"] == EMBEDDING_DIM
    assert len(body["vector"]) == EMBEDDING_DIM

    repeat = await client.post("/v1/embed", json={"text": "when do I hear back?"})
    assert repeat.json()["vector"] == body["vector"]


async def test_media_backends_lists_embedder(client: httpx.AsyncClient) -> None:
    response = await client.get("/media-backends")
    assert response.status_code == 200
    assert "embed" in response.json()
