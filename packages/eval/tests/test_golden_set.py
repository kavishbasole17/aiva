import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

GATEWAY_URL = os.environ.get("AIVA_EVAL_GATEWAY_URL")
CASES_PATH = Path(__file__).resolve().parent.parent / "golden" / "cases.jsonl"

requires_gateway = pytest.mark.skipif(
    GATEWAY_URL is None,
    reason="gateway URL not set (AIVA_EVAL_GATEWAY_URL)",
)

CASES = [json.loads(line) for line in CASES_PATH.read_text().splitlines() if line.strip()]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    assert GATEWAY_URL is not None
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=10.0) as http_client:
        yield http_client


@requires_gateway
@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
async def test_golden_case_is_schema_valid_and_deterministic(
    client: httpx.AsyncClient,
    case: dict[str, object],
) -> None:
    payload = {
        "prompt_id": case["prompt_id"],
        "response_model": case["response_model"],
        "inputs": case["inputs"],
        "seed_key": case["seed_key"],
    }
    first = await client.post("/v1/generate", json=payload)
    assert first.status_code == 200, f"{case['case_id']}: {first.text}"
    body = first.json()

    second = await client.post("/v1/generate", json=payload)
    assert second.status_code == 200
    assert second.json()["data"] == body["data"], "determinism violated"

    data = body["data"]
    if case["response_model"] == "DimensionScore":
        assert isinstance(data["score"], int)
        assert 0 <= int(data["score"]) <= 100
        assert len(data["cited_span_ids"]) >= 1
    else:
        assert str(data.get("source_quote", "")).strip()
