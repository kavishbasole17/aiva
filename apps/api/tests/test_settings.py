import pathlib

import pytest
from pydantic import ValidationError

from app.settings import Settings

REQUIRED = {
    "AIVA_DATABASE_URL": "postgresql+asyncpg://aiva:aiva@db:5432/aiva",
    "AIVA_REDIS_URL": "redis://redis:6379/0",
    "AIVA_MINIO_ENDPOINT": "minio:9000",
    "AIVA_MINIO_ACCESS_KEY": "key",
    "AIVA_MINIO_SECRET_KEY": "secret",
    "AIVA_MINIO_BUCKET": "bucket",
}


def test_missing_required_variable_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in REQUIRED:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_valid_environment_parses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AIVA_MINIO_SECURE", "true")
    settings = Settings()
    assert settings.minio_secure is True
    assert settings.log_level == "INFO"
    assert settings.environment == "development"


def test_invalid_bucket_name_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AIVA_MINIO_BUCKET", "no")
    with pytest.raises(ValidationError):
        Settings()
