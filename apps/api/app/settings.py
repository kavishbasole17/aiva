import base64
from functools import lru_cache

from pydantic import Field, field_validator
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
    encryption_key: str = Field(min_length=1)
    ai_gateway_url: str = ""
    sandbox_url: str = ""
    invite_token_days: int = 14
    interview_token_hours: int = 48
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    log_level: str = "INFO"
    environment: str = "development"
    email_backend: str = "log"
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_from_addr: str = "no-reply@aiva.local"
    email_smtp_use_tls: bool = True
    candidate_portal_url: str = "http://localhost:15174"

    @field_validator("encryption_key")
    @classmethod
    def _validate_encryption_key(cls, value: str) -> str:
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:
            raise ValueError("AIVA_ENCRYPTION_KEY must be base64-encoded (32 raw bytes)") from exc
        if len(raw) != 32:
            raise ValueError(f"AIVA_ENCRYPTION_KEY must decode to exactly 32 bytes, got {len(raw)}")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
