from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIVA_GATEWAY_", frozen=True, extra="ignore")

    llm_backend: str = "mock"
    prompts_dir: str = ""
    vllm_base_url: str = ""
    vllm_model: str = "Qwen2.5-14B-Instruct-AWQ"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
