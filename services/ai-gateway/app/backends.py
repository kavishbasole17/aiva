import hashlib
import json
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
        if name == "confidence":
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


class VllmBackend(Backend):
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

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
        del inputs
        import httpx

        model_type = get_response_model(response_model_name)
        guided_schema = json.dumps(model_type.model_json_schema())
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": rendered_prompt}],
            "temperature": 0,
            "seed": int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16),
            "guided_json": guided_schema,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()

        content = body["choices"][0]["message"]["content"]
        try:
            parsed: dict[str, object] = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Model returned non-JSON despite guided decoding") from exc
        try:
            validated = model_type.model_validate(parsed)
        except ValidationError as exc:
            raise RuntimeError(f"Schema-invalid model output: {exc}") from exc
        return validated.model_dump(), self.model_id


def build_backend(backend_name: str, vllm_base_url: str, vllm_model: str) -> Backend:
    if backend_name == "mock":
        return MockBackend()
    if backend_name == "vllm":
        if not vllm_base_url:
            raise ValueError("AIVA_GATEWAY_VLLM_BASE_URL required for vllm backend")
        return VllmBackend(vllm_base_url, vllm_model)
    raise ValueError(f"Unknown backend: {backend_name}")


__all__ = [
    "Backend",
    "GenerationResult",
    "MockBackend",
    "PromptRegistry",
    "VllmBackend",
    "build_backend",
]
