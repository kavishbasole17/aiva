import hashlib
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError

from app.contracts import get_response_model
from app.prompts import PromptRegistry


class GenerationResult(BaseModel):
    data: dict[str, object]
    prompt_version: str
    backend: str
    model_id: str


def _deterministic_fill(
    model_type: type[BaseModel],
    seed_text: str,
    inputs: dict[str, str],
) -> dict[str, object]:
    schema = model_type.model_json_schema()
    properties: dict[str, object] = schema.get("properties", {})
    seed_bytes = hashlib.sha256(seed_text.encode("utf-8")).digest()
    filled: dict[str, object] = {}
    for index, (name, spec) in enumerate(sorted(properties.items())):
        spec_dict: dict[str, object] = spec  # type: ignore[assignment]
        field_type = str(spec_dict.get("type", "string"))
        byte = seed_bytes[index % len(seed_bytes)]
        enum_values = spec_dict.get("enum")
        if isinstance(enum_values, list) and enum_values:
            # A Literal/enum-constrained field (e.g. a fixed set of
            # recommendation verdicts): the generic string branch below
            # would synthesize a value matching no allowed choice, failing
            # this same model's own validation a few lines later. Picking
            # deterministically from the real allowed set keeps the mock
            # backend's "byte-seeded but always schema-valid" guarantee
            # intact for any current or future enum-typed contract field,
            # not just recommendation specifically.
            filled[name] = enum_values[byte % len(enum_values)]
        elif name == "confidence":
            filled[name] = round(0.5 + (byte / 510), 2)
        elif field_type == "integer":
            minimum_raw = spec_dict.get("minimum", 0)
            maximum_raw = spec_dict.get("maximum", 100)
            low = minimum_raw if isinstance(minimum_raw, int) else 0
            high = maximum_raw if isinstance(maximum_raw, int) else 100
            filled[name] = low + (byte % (high - low + 1))
        elif field_type == "number":
            filled[name] = round(byte / 255, 2)
        elif field_type == "array":
            item_spec = spec_dict.get("items", {})
            item_type = (
                str(item_spec.get("type", "string")) if isinstance(item_spec, dict) else "string"
            )
            if item_type == "string":
                filled[name] = [f"span-{byte:02x}"]
            else:
                filled[name] = [byte]
        elif field_type == "boolean":
            filled[name] = bool(byte % 2)
        else:
            filled[name] = inputs.get(name) or f"synthetic-{name}:{seed_text[:16]}"
    return filled


class Backend(ABC):
    @abstractmethod
    async def generate(
        self,
        rendered_prompt: str,
        response_model_name: str,
        seed_key: str,
        inputs: dict[str, str] | None = None,
    ) -> tuple[dict[str, object], str]: ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        pass


class MockBackend(Backend):
    @property
    def model_id(self) -> str:
        return "aiva-mock-deterministic"

    async def generate(
        self,
        rendered_prompt: str,
        response_model_name: str,
        seed_key: str,
        inputs: dict[str, str] | None = None,
    ) -> tuple[dict[str, object], str]:
        model_type = get_response_model(response_model_name)
        raw = _deterministic_fill(
            model_type,
            f"{response_model_name}:{rendered_prompt}:{seed_key}",
            inputs or {},
        )
        validated = model_type.model_validate(raw)
        return validated.model_dump(), self.model_id


class AnthropicBackend(Backend):
    """Real inference via the hosted Anthropic API.

    Replaces the previous hand-rolled local/self-hosted model path (a bespoke
    vLLM client expecting operator-managed GPU weights). Structured output is
    obtained the same way `VllmBackend` used `guided_json`: the response
    model's JSON schema is registered as a single forced tool, so the model's
    only possible reply is a schema-shaped `tool_use` block — no free-text
    parsing, no "hope it's valid JSON." Pydantic validates the tool input
    before it's ever trusted (ADR-024).

    Determinism note: `temperature=0` makes output *close to* deterministic
    but the hosted API gives no hard reproducibility guarantee the way a
    pinned local weight + fixed seed would. Unlike `MockBackend`, repeated
    calls are not guaranteed byte-identical — documented honestly rather than
    faked, same discipline as every other capability gap in this repo.
    """

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("AIVA_GATEWAY_ANTHROPIC_API_KEY required for anthropic backend")
        self.model = model
        self._api_key = api_key

    @property
    def model_id(self) -> str:
        return self.model

    async def generate(
        self,
        rendered_prompt: str,
        response_model_name: str,
        seed_key: str,
        inputs: dict[str, str] | None = None,
    ) -> tuple[dict[str, object], str]:
        del inputs, seed_key
        from anthropic import AsyncAnthropic

        model_type = get_response_model(response_model_name)
        schema = model_type.model_json_schema()
        tool_name = f"emit_{response_model_name.lower()}"

        client = AsyncAnthropic(api_key=self._api_key)
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0,
                messages=[{"role": "user", "content": rendered_prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": f"Emit a {response_model_name} judgement.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )
        finally:
            await client.close()

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise RuntimeError("Anthropic response contained no tool_use block")
        try:
            validated = model_type.model_validate(tool_use.input)
        except ValidationError as exc:
            raise RuntimeError(f"Schema-invalid model output: {exc}") from exc
        return validated.model_dump(), self.model_id


def build_backend(backend_name: str, anthropic_api_key: str, anthropic_model: str) -> Backend:
    if backend_name == "mock":
        return MockBackend()
    if backend_name == "anthropic":
        return AnthropicBackend(anthropic_api_key, anthropic_model)
    raise ValueError(f"Unknown backend: {backend_name}")


__all__ = [
    "AnthropicBackend",
    "Backend",
    "GenerationResult",
    "MockBackend",
    "PromptRegistry",
    "build_backend",
]
