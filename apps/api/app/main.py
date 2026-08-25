from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import create_session_factory
from app.health import Dependencies, setup_dependencies
from app.health import router as health_router
from app.logging_setup import configure_logging
from app.routers_audit import router as audit_router
from app.routers_auth import router as auth_router
from app.routers_org import router as org_router
from app.routers_questionnaire import router as questionnaire_router
from app.routers_resume import router as resume_router
from app.routers_scheduling import router as scheduling_router
from app.security_headers import SecurityHeadersMiddleware
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    override: Settings | None = app.state.settings_override
    settings = override if override is not None else get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.deps = await setup_dependencies(settings)
    app.state.session_factory = create_session_factory(settings)
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
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(org_router)
    app.include_router(resume_router)
    app.include_router(questionnaire_router)
    app.include_router(scheduling_router)
    app.include_router(audit_router)
    return app


app = create_app()
