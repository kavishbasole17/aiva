from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.backends import Backend, GenerationResult, PromptRegistry, build_backend
from app.contracts import get_response_model
from app.logging_setup import configure_logging
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    override: Settings | None = app.state.settings_override
    settings = override if override is not None else get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.backend = build_backend(
        settings.llm_backend, settings.vllm_base_url, settings.vllm_model
    )
    prompts_dir = Path(settings.prompts_dir) if settings.prompts_dir else None
    app.state.prompts = PromptRegistry(prompts_dir)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="AIVA AI Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings_override = settings
    app.include_router(router)
    return app


class GenerateRequest(BaseModel):
    prompt_id: str
    response_model: str
    inputs: dict[str, str] = Field(default_factory=dict)
    seed_key: str = "default"


class GenerateResponse(BaseModel):
    data: dict[str, Any]
    prompt_version: str
    backend: str
    model_id: str


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/prompts")
async def list_prompts(request: Request) -> dict[str, object]:
    registry: PromptRegistry = request.app.state.prompts
    prompts = [{"id": pid, "version": registry.get(pid).version} for pid in registry.list_ids()]
    return {"prompts": prompts}


@router.post("/v1/generate", response_model=GenerateResponse)
async def generate(body: GenerateRequest, request: Request) -> GenerateResponse:
    try:
        get_response_model(body.response_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    registry: PromptRegistry = request.app.state.prompts
    try:
        prompt = registry.get(body.prompt_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    backend: Backend = request.app.state.backend
    missing = [key for key in _required_inputs(prompt.template) if key not in body.inputs]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing prompt inputs: {missing}")

    rendered = prompt.render(body.inputs)
    data, model_id = await backend.generate(
        rendered, body.response_model, body.seed_key, body.inputs
    )
    result = GenerationResult(
        data=data,
        prompt_version=prompt.version,
        backend=request.app.state.settings.llm_backend,
        model_id=model_id,
    )
    return GenerateResponse(
        data=result.data,
        prompt_version=result.prompt_version,
        backend=result.backend,
        model_id=result.model_id,
    )


def _required_inputs(template: str) -> list[str]:
    import re

    return re.findall(r"\{\{(\w+)\}\}", template)


app = create_app()
