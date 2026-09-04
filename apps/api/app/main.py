from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import create_session_factory
from app.health import Dependencies, setup_dependencies
from app.health import router as health_router
from app.logging_setup import configure_logging
from app.rate_limit import limiter
from app.routers_audit import router as audit_router
from app.routers_auth import router as auth_router
from app.routers_dashboard import router as dashboard_router
from app.routers_dsar import router as dsar_router
from app.routers_evaluation import router as evaluation_router
from app.routers_faq import router as faq_router
from app.routers_integrity import router as integrity_router
from app.routers_interview import router as interview_router
from app.routers_org import router as org_router
from app.routers_questionnaire import router as questionnaire_router
from app.routers_resume import router as resume_router
from app.routers_retention import router as retention_router
from app.routers_scheduling import router as scheduling_router
from app.routers_workspace import router as workspace_router
from app.security_headers import SecurityHeadersMiddleware
from app.settings import Settings, get_settings


async def _handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover - only registered for this type
        raise TypeError(f"expected RateLimitExceeded, got {type(exc).__name__}")
    return _rate_limit_exceeded_handler(request, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    override: Settings | None = app.state.settings_override
    settings = override if override is not None else get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.deps = await setup_dependencies(settings)
    app.state.session_factory = create_session_factory(settings)
    # Rate limiting is a shared, process-wide in-memory counter (see
    # app/rate_limit.py). Disabled only for `environment=test`, where many
    # separate test app instances share one Python process/counter within a
    # single pytest run and would otherwise spuriously 429 each other.
    limiter.enabled = settings.environment != "test"
    yield
    deps: Dependencies = app.state.deps
    await deps.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="AIVA API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings_override = settings
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(org_router)
    app.include_router(resume_router)
    app.include_router(questionnaire_router)
    app.include_router(scheduling_router)
    app.include_router(interview_router)
    app.include_router(integrity_router)
    app.include_router(workspace_router)
    app.include_router(faq_router)
    app.include_router(evaluation_router)
    app.include_router(dsar_router)
    app.include_router(retention_router)
    app.include_router(dashboard_router)
    app.include_router(audit_router)
    return app


app = create_app()
