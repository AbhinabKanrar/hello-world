"""Runtime settings. Override any field with env vars prefixed SOCIETY_ (e.g. SOCIETY_CHAT_MODEL)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SOCIETY_", frozen=True, extra="ignore"
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "llama3.1:8b"
    embed_model: str = "nomic-embed-text"

    concurrency: int = Field(
        8, ge=1, le=256, description="Max in-flight LLM requests."
    )
    request_timeout_s: float = Field(120.0, gt=0)
    max_retries: int = Field(
        4, ge=0, description="Retries for transient transport errors."
    )
    max_validation_retries: int = Field(
        2, ge=0, description="Retries when output fails schema."
    )
    retry_base_delay_s: float = Field(0.5, gt=0)

    embed_batch_size: int = Field(64, ge=1, le=512)
    cache_path: Path = Path(".society/cache.sqlite")
