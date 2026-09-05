import httpx

VALID_INPUTS = {
    "dimension": "technical",
    "score_range_note": "0-100",
    "jd_clause": "5 years of Python",
    "candidate_spans": "span-01: built backend services",
}


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200


async def test_prompts_listed_with_versions(client: httpx.AsyncClient) -> None:
    response = await client.get("/prompts")
    assert response.status_code == 200
    prompts = response.json()["prompts"]
    assert {"id": "dimension_score", "version": prompts[0]["version"]} in prompts
    assert len(prompts[0]["version"]) == 16


async def test_generate_returns_schema_valid_deterministic_output(
    client: httpx.AsyncClient,
) -> None:
    request_payload = {
        "prompt_id": "dimension_score",
        "response_model": "DimensionScore",
        "inputs": VALID_INPUTS,
        "seed_key": "candidate-42",
    }
    first = await client.post("/v1/generate", json=request_payload)
    assert first.status_code == 200, first.text
    body_first = first.json()
    data = body_first["data"]
    assert isinstance(data["score"], int)
    assert 0 <= data["score"] <= 100
    assert 0.0 <= data["confidence"] <= 1.0
    assert len(data["cited_span_ids"]) >= 1
    assert data["rationale"]

    second = await client.post("/v1/generate", json=request_payload)
    assert second.json()["data"] == body_first["data"]

    different_inputs = dict(request_payload, inputs=dict(VALID_INPUTS, dimension="communication"))
    fourth = await client.post("/v1/generate", json=different_inputs)
    assert fourth.json()["data"]["dimension"] == "communication"
    assert fourth.json()["prompt_version"] == body_first["prompt_version"]


async def test_unknown_prompt_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/generate",
        json={"prompt_id": "nope", "response_model": "DimensionScore", "inputs": {}},
    )
    assert response.status_code == 404


async def test_unknown_response_model_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/generate",
        json={"prompt_id": "dimension_score", "response_model": "Nope", "inputs": VALID_INPUTS},
    )
    assert response.status_code == 400


async def test_missing_prompt_inputs_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/generate",
        json={"prompt_id": "dimension_score", "response_model": "DimensionScore", "inputs": {}},
    )
    assert response.status_code == 400
    assert "Missing prompt inputs" in response.json()["detail"]


QUESTIONNAIRE_EVAL_INPUTS = {
    "jd_clause": "5 years of Python, remote-first",
    "qa_pairs": "notice_period: What is your notice period? -> 2 weeks",
    "resume_spans": "span-01: 5 years Python backend experience",
}


async def test_questionnaire_evaluation_is_schema_valid_and_deterministic(
    client: httpx.AsyncClient,
) -> None:
    """Regression test for a real bug: QuestionnaireEvaluation's `recommendation`
    is an enum-constrained field, and MockBackend's deterministic fill
    originally had no enum handling -- it synthesized a placeholder string
    matching none of the allowed values, failing this same model's own
    validation. Fixed in backends.py's _deterministic_fill; this test proves
    the fix, not just that the endpoint returns 200."""
    request_payload = {
        "prompt_id": "questionnaire_evaluation",
        "response_model": "QuestionnaireEvaluation",
        "inputs": QUESTIONNAIRE_EVAL_INPUTS,
        "seed_key": "response-1",
    }
    first = await client.post("/v1/generate", json=request_payload)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["recommendation"] in {"proceed", "hold", "reject"}
    assert 0 <= data["overall_score"] <= 100
    assert isinstance(data["inconsistencies"], list)
    assert isinstance(data["missing_critical_info"], list)
    assert len(data["cited_span_ids"]) >= 1

    second = await client.post("/v1/generate", json=request_payload)
    assert second.json()["data"] == data
