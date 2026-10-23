"""Runtime settings. Override any field with env vars prefixed SOCIETY_ (e.g. SOCIETY_CHAT_MODEL)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOCIETY_", frozen=True, extra="ignore")

    ollama_base_url: str = "http://127.0.0.1:11434"
    provider: Literal["ollama", "openrouter"] = "openrouter"
    chat_model: str = "openai/gpt-oss-120b"
    embed_model: str = "qwen/qwen3-embedding-8b"

    openrouter_api_key: SecretStr | None = None
    openrouter_providers: tuple[str, ...] = ("near-ai", "venice", "coreweave", "dekallm", "deepinfra")
    openrouter_allow_fallbacks: bool = True
    openrouter_send_seed: bool = True
    openrouter_reasoning_effort: Literal["low", "medium", "high"] | None = "low"
    openrouter_max_tokens: int = Field(16384, ge=256, le=131_072)
    openrouter_call_timeout_s: float = Field(300.0, gt=0, allow_inf_nan=False)
    openrouter_max_retry_delay_s: float = Field(60.0, gt=0, allow_inf_nan=False)

    concurrency: int = Field(4, ge=1, le=256, description="Max in-flight LLM requests.")
    request_timeout_s: float = Field(120.0, gt=0)
    max_retries: int = Field(4, ge=0, description="Retries for transient transport errors.")
    max_validation_retries: int = Field(2, ge=0, description="Retries when output fails schema.")
    retry_base_delay_s: float = Field(0.5, gt=0)

    embed_batch_size: int = Field(64, ge=1, le=512)
    cache_path: Path = Path(".society/cache.sqlite")
