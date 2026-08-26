from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.backends import Backend, GenerationResult, PromptRegistry, build_backend
from app.contracts import get_response_model
from app.embeddings import MAX_EMBED_CHARS, EmbeddingProvider, build_embedder
from app.logging_setup import configure_logging
from app.media import (
    MAX_SYNTH_CHARS,
    MediaError,
    SpeechProvider,
    TranscriptionProvider,
    build_speaker,
    build_transcriber,
    decode_audio,
)
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
    app.state.stt = build_transcriber(settings.stt_backend, settings.stt_model)
    app.state.tts = build_speaker(settings.tts_backend, settings.tts_voice)
    app.state.embedder = build_embedder(settings.embed_backend, settings.embed_model)
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


class SttRequest(BaseModel):
    audio_b64: str = Field(min_length=1)
    language: str = Field(default="en", min_length=2, max_length=16)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SYNTH_CHARS)


class EmbedRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_EMBED_CHARS)


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/prompts")
async def list_prompts(request: Request) -> dict[str, object]:
    registry: PromptRegistry = request.app.state.prompts
    prompts = [{"id": pid, "version": registry.get(pid).version} for pid in registry.list_ids()]
    return {"prompts": prompts}


@router.get("/media-backends")
async def media_backends(request: Request) -> dict[str, object]:
    stt: TranscriptionProvider = request.app.state.stt
    tts: SpeechProvider = request.app.state.tts
    embedder: EmbeddingProvider = request.app.state.embedder
    return {
        "stt": {"provider": type(stt).__name__, "model_id": stt.model_id},
        "tts": {"provider": type(tts).__name__, "model_id": tts.model_id},
        "embed": {"provider": type(embedder).__name__, "model_id": embedder.model_id},
    }


@router.post("/v1/stt")
async def stt(body: SttRequest, request: Request) -> dict[str, object]:
    try:
        audio = decode_audio(body.audio_b64)
    except MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    transcriber: TranscriptionProvider = request.app.state.stt
    result = await transcriber.transcribe(audio, body.language)
    return result.model_dump()


@router.post("/v1/tts")
async def tts(body: TtsRequest, request: Request) -> dict[str, object]:
    speaker: SpeechProvider = request.app.state.tts
    result = await speaker.synthesize(body.text)
    return result.model_dump()


@router.post("/v1/embed")
async def embed(body: EmbedRequest, request: Request) -> dict[str, object]:
    embedder: EmbeddingProvider = request.app.state.embedder
    result = await embedder.embed(body.text)
    return result.model_dump()


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
