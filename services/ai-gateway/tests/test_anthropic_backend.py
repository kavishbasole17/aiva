"""Unit tests for AnthropicBackend's structured-output extraction.

Mocks the Anthropic SDK client entirely — no network calls, no API key needed —
and proves the contract that matters: a forced tool_use block is parsed and
validated against the response model, and schema-invalid tool input is
rejected rather than silently passed through (same discipline as
VllmBackend's guided-decoding validation it replaces).
"""

from dataclasses import dataclass
from typing import Any

import pytest

from app.backends import AnthropicBackend


@dataclass
class FakeToolUseBlock:
    input: dict[str, Any]
    type: str = "tool_use"
    name: str = "emit_dimensionscore"


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeMessage:
    content: list[Any]


class FakeMessages:
    def __init__(self, response: FakeMessage) -> None:
        self._response = response
        self.last_call_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> FakeMessage:
        self.last_call_kwargs = kwargs
        return self._response


class FakeAsyncAnthropic:
    def __init__(self, response: FakeMessage, **_: Any) -> None:
        self.messages = FakeMessages(response)

    async def close(self) -> None:
        pass


VALID_TOOL_INPUT = {
    "dimension": "technical",
    "score": 82,
    "rationale": "Strong match against required skills.",
    "confidence": 0.9,
    "cited_span_ids": ["span-01"],
}


async def test_anthropic_backend_parses_and_validates_tool_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_response = FakeMessage(content=[FakeToolUseBlock(input=VALID_TOOL_INPUT)])
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic", lambda **kwargs: FakeAsyncAnthropic(fake_response, **kwargs)
    )

    backend = AnthropicBackend(api_key="test-key", model="claude-sonnet-5")
    data, model_id = await backend.generate(
        rendered_prompt="Score this candidate.",
        response_model_name="DimensionScore",
        seed_key="candidate-1",
    )

    assert data["score"] == 82
    assert data["dimension"] == "technical"
    assert model_id == "claude-sonnet-5"


async def test_anthropic_backend_forces_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_response = FakeMessage(content=[FakeToolUseBlock(input=VALID_TOOL_INPUT)])
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeAsyncAnthropic:
        client = FakeAsyncAnthropic(fake_response, **kwargs)
        captured["client"] = client
        return client

    monkeypatch.setattr("anthropic.AsyncAnthropic", factory)

    backend = AnthropicBackend(api_key="test-key", model="claude-sonnet-5")
    await backend.generate(
        rendered_prompt="Score this candidate.",
        response_model_name="DimensionScore",
        seed_key="candidate-1",
    )

    call_kwargs = captured["client"].messages.last_call_kwargs
    assert call_kwargs is not None
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "emit_dimensionscore"}
    assert call_kwargs["temperature"] == 0
    assert call_kwargs["tools"][0]["name"] == "emit_dimensionscore"


async def test_anthropic_backend_rejects_schema_invalid_tool_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_input = {**VALID_TOOL_INPUT, "score": 200}  # out of 0-100 range
    fake_response = FakeMessage(content=[FakeToolUseBlock(input=invalid_input)])
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic", lambda **kwargs: FakeAsyncAnthropic(fake_response, **kwargs)
    )

    backend = AnthropicBackend(api_key="test-key", model="claude-sonnet-5")
    with pytest.raises(RuntimeError, match="Schema-invalid model output"):
        await backend.generate(
            rendered_prompt="Score this candidate.",
            response_model_name="DimensionScore",
            seed_key="candidate-1",
        )


async def test_anthropic_backend_rejects_missing_tool_use_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_response = FakeMessage(content=[FakeTextBlock(text="I refuse to use the tool.")])
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic", lambda **kwargs: FakeAsyncAnthropic(fake_response, **kwargs)
    )

    backend = AnthropicBackend(api_key="test-key", model="claude-sonnet-5")
    with pytest.raises(RuntimeError, match="no tool_use block"):
        await backend.generate(
            rendered_prompt="Score this candidate.",
            response_model_name="DimensionScore",
            seed_key="candidate-1",
        )


def test_anthropic_backend_requires_api_key() -> None:
    with pytest.raises(ValueError, match="AIVA_GATEWAY_ANTHROPIC_API_KEY"):
        AnthropicBackend(api_key="", model="claude-sonnet-5")
