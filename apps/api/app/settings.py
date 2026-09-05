from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIVA_",
        env_file=".env",
        frozen=True,
        extra="ignore",
    )

    database_url: str
    admin_database_url: str | None = None
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = Field(min_length=3, max_length=63)
    minio_secure: bool = False
    jwt_secret: str = Field(min_length=24)
    ai_gateway_url: str = ""
    sandbox_url: str = ""
    invite_token_days: int = 14
    interview_token_hours: int = 48
    retention_days: int = Field(default=730, ge=1)
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    log_level: str = "INFO"
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
