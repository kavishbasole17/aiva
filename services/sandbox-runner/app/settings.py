from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIVA_SANDBOX_", frozen=True, extra="ignore")

    default_timeout_seconds: float = 5.0
    max_timeout_seconds: float = 15.0
    memory_limit_mb: int = 256
    node_memory_limit_mb: int = 128
    node_rlimit_as_mb: int = 768
    max_processes: int = 16
    max_open_files: int = 64
    max_source_bytes: int = 65_536
    max_output_bytes: int = 65_536
    # Dedicated unprivileged accounts the Dockerfile creates for running
    # candidate code, distinct from the service's own account (ADR-019) and
    # from each other: every concurrently-executing run gets its own uid
    # out of this pool, never a shared one (ADR-020) — sharing a uid across
    # concurrent runs would let one run read/kill another's via matching
    # filesystem ownership. 6666..6666+size-1 matches the fixed uid range
    # the Dockerfile pins for the `sandbox0`..`sandboxN` system users, all
    # sharing gid 6666. Outside that image (e.g. bare host dev),
    # _drop_privileges only takes effect when running as real root anyway,
    # so unresolved uids here are harmless — see executors.py.
    sandbox_uid_pool_start: int = 6666
    sandbox_uid_pool_size: int = 32
    sandbox_gid: int = 6666
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
