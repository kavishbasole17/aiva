import os
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import create_app

OFFLINE_SETTINGS = {
    "AIVA_DATABASE_URL": "postgresql+asyncpg://aiva:aiva@127.0.0.1:9/aiva",
    "AIVA_REDIS_URL": "redis://127.0.0.1:9/0",
    "AIVA_MINIO_ENDPOINT": "127.0.0.1:9",
    "AIVA_MINIO_ACCESS_KEY": "offline",
    "AIVA_MINIO_SECRET_KEY": "offline-secret",
    "AIVA_MINIO_BUCKET": "offline-bucket",
    "AIVA_JWT_SECRET": "unit-test-jwt-secret-0123456789abcdef",
    "AIVA_ENCRYPTION_KEY": "b2ZmbGluZS10ZXN0LWtleS0zMi1ieXRlcy1sb25nISE=",
    "AIVA_ENVIRONMENT": "test",
}


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("AIVA_INTEGRATION") == "1":
        return
    for key, value in OFFLINE_SETTINGS.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client:
            yield test_client
