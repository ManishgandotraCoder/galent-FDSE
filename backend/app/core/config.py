"""Settings loaded from the environment.

Copy `backend/.env.example` to `backend/.env` and change only what you need.
Every name uses the `AP_` prefix, so `AP_LOG_LEVEL` sets `log_level`.
Call `get_settings()` instead of reading `os.environ` anywhere else.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file is backend/app/core/config.py, so two parents up is backend/.
BACKEND_ROOT = Path(__file__).resolve().parents[2]

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_prefix="AP_",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = Field(
        default="local",
        validation_alias=AliasChoices("AP_ENV", "AP_ENVIRONMENT"),
    )
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    data_dir: Path = BACKEND_ROOT / "data"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    max_files: int = 20
    max_file_bytes: int = 20 * 1024 * 1024
    auto_clear_confidence: float = 0.95
    flag_confidence: float = 0.70
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    ollama_max_in_flight: int = 2
    model_max_chars: int = 24000
    read_workers: int = 8
    redis_url: str = "redis://127.0.0.1:6379/0"
    cache_ttl_seconds: int = 7 * 24 * 60 * 60

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in LOG_LEVELS:
            allowed = ", ".join(sorted(LOG_LEVELS))
            raise ValueError(f"AP_LOG_LEVEL must be one of: {allowed}.")
        return level

    @model_validator(mode="after")
    def check_ranges(self) -> "Settings":
        if not 0 <= self.flag_confidence <= self.auto_clear_confidence <= 1:
            raise ValueError(
                "AP_FLAG_CONFIDENCE must be between 0 and AP_AUTO_CLEAR_CONFIDENCE, "
                "and AP_AUTO_CLEAR_CONFIDENCE must be at most 1."
            )
        if self.max_files < 1 or self.max_file_bytes < 1:
            raise ValueError("AP_MAX_FILES and AP_MAX_FILE_BYTES must be at least 1.")
        if self.ollama_max_in_flight < 1 or self.read_workers < 1 or self.model_max_chars < 1:
            raise ValueError("AP_OLLAMA_MAX_IN_FLIGHT, AP_READ_WORKERS, and AP_MODEL_MAX_CHARS must be at least 1.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def redis_target(self) -> str:
        """Host and database only. A password in the URL is left out of logs."""
        parsed = urlparse(self.redis_url)
        host = parsed.hostname or "redis"
        port = parsed.port or 6379
        database = parsed.path.lstrip("/") or "0"
        return f"{host}:{port}/{database}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
