from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.executors import (
    SUPPORTED_LANGUAGES,
    ExecutionResult,
    SandboxError,
    SandboxUnavailableError,
    UidPool,
    build_executor,
)
from app.logging_setup import configure_logging
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    override: Settings | None = app.state.settings_override
    settings = override if override is not None else get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    # One pool for the process lifetime: every concurrent execution checks
    # out a distinct uid and returns it when done, so no two runs ever share
    # one (ADR-020) — asyncio.Queue-backed, so acquire() naturally blocks
    # rather than falling back to something shared when the pool is empty.
    app.state.uid_pool = UidPool(
        settings.sandbox_uid_pool_start, settings.sandbox_uid_pool_size, settings.sandbox_gid
    )
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="AIVA Sandbox Runner",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings_override = settings
    app.include_router(router)
    return app


class ExecuteRequest(BaseModel):
    language: str
    source: str = Field(min_length=1)
    stdin: str = Field(default="", max_length=65_536)
    timeout_seconds: float | None = None


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/runtimes")
async def runtimes(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "languages": list(SUPPORTED_LANGUAGES),
        "isolation": {
            "kind": "process-rlimit+per-run-uid+netns+pidns",
            "network": "isolated (no route to host or internet)",
            "note": "process-level isolation, not a container/VM boundary — see app/executors.py",
        },
        "default_timeout_seconds": settings.default_timeout_seconds,
        "max_timeout_seconds": settings.max_timeout_seconds,
    }


@router.post("/v1/execute", response_model=ExecutionResult)
async def execute(body: ExecuteRequest, request: Request) -> ExecutionResult:
    settings: Settings = request.app.state.settings
    if len(body.source.encode("utf-8")) > settings.max_source_bytes:
        raise HTTPException(
            status_code=400, detail=f"source exceeds {settings.max_source_bytes} byte cap"
        )
    timeout = body.timeout_seconds or settings.default_timeout_seconds
    timeout = max(0.1, min(timeout, settings.max_timeout_seconds))

    try:
        executor = build_executor(body.language)
    except SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pool: UidPool = request.app.state.uid_pool
    uid = await pool.acquire()
    try:
        return await executor.run(body.source, body.stdin, timeout, uid, pool.gid)
    except SandboxUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        pool.release(uid)


app = create_app()
