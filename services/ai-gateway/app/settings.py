from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIVA_GATEWAY_", frozen=True, extra="ignore")

    llm_backend: str = "mock"
    prompts_dir: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    stt_backend: str = "mock"
    stt_model: str = "faster-whisper-large-v3"
    tts_backend: str = "mock"
    tts_voice: str = "piper-onnx-en_US-lessac-medium"
    embed_backend: str = "mock"
    embed_model: str = "all-MiniLM-L6-v2"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
