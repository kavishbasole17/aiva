import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass

import redis.asyncio as aioredis
import urllib3
from fastapi import APIRouter, Request, Response
from minio import Minio
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings import Settings

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 2.0


@dataclass
class Dependencies:
    engine: AsyncEngine
    redis: aioredis.Redis
    minio: Minio

    async def aclose(self) -> None:
        await self.engine.dispose()
        await self.redis.aclose()


def _probe_http_pool(secure: bool) -> urllib3.PoolManager:
    return urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=1.0, read=CHECK_TIMEOUT_SECONDS),
        retries=False,
        cert_reqs="CERT_REQUIRED" if secure else "CERT_NONE",
    )


async def setup_dependencies(settings: Settings) -> Dependencies:
    return Dependencies(
        engine=create_async_engine(settings.database_url, pool_pre_ping=True),
        # redis-py ships an untyped from_url; only ping/aclose are used against it.
        redis=aioredis.from_url(settings.redis_url),  # type: ignore[no-untyped-call]
        minio=Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            http_client=_probe_http_pool(settings.minio_secure),
        ),
    )


class ReadinessCheck(BaseModel):
    postgres: str
    redis: str
    minio: str


class ReadinessReport(BaseModel):
    status: str
    checks: ReadinessCheck


async def _check_postgres(deps: Dependencies) -> str:
    async with deps.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return "up"


async def _check_redis(deps: Dependencies) -> str:
    await deps.redis.ping()
    return "up"


async def _check_minio(deps: Dependencies, bucket: str) -> str:
    exists = await asyncio.to_thread(deps.minio.bucket_exists, bucket)
    return "up" if exists else "missing_bucket"


async def _guarded(check: Awaitable[str]) -> str:
    try:
        return await asyncio.wait_for(check, CHECK_TIMEOUT_SECONDS)
    except Exception:
        return "down"


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    deps: Dependencies = request.app.state.deps
    settings: Settings = request.app.state.settings

    postgres, redis_state, minio_state = await asyncio.gather(
        _guarded(_check_postgres(deps)),
        _guarded(_check_redis(deps)),
        _guarded(_check_minio(deps, settings.minio_bucket)),
    )
    checks = ReadinessCheck(postgres=postgres, redis=redis_state, minio=minio_state)
    all_up = all(value == "up" for value in checks.model_dump().values())
    response.status_code = 200 if all_up else 503
    return ReadinessReport(status="ok" if all_up else "degraded", checks=checks).model_dump()
