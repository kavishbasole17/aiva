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
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = Field(min_length=3, max_length=63)
    minio_secure: bool = False
    log_level: str = "INFO"
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    # Fields are populated from AIVA_* environment variables at process start;
    # requiring them as constructor args would defeat fail-closed env validation.
    return Settings()  # type: ignore[call-arg]
