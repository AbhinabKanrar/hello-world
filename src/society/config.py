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
    openrouter_reasoning_effort: Literal["low", "medium", "high"] | None = "medium"
    openrouter_max_tokens: int = Field(31_072, ge=256, le=131_072)
    openrouter_call_timeout_s: float = Field(300.0, gt=0, allow_inf_nan=False)
    openrouter_max_retry_delay_s: float = Field(60.0, gt=0, allow_inf_nan=False)

    # Batch API (POST /batches). Independent requests are grouped into chunks bounded by
    # both request count and serialized bytes, submitted with a bounded in-flight window,
    # polled to a final status, and results are matched by custom_id.
    openrouter_batch_enabled: bool = True
    openrouter_batch_min_requests: int = Field(
        32, ge=1, description="Fewer requests than this use the synchronous path."
    )
    openrouter_batch_max_requests: int = Field(
        5_000, ge=1, description="Per-batch request cap; lowered automatically on HTTP 413."
    )
    openrouter_batch_max_bytes: int = Field(
        128 << 20, ge=1 << 20, le=200 << 20, description="Per-batch serialized body cap."
    )
    openrouter_batch_max_in_flight: int = Field(3, ge=1, le=16)
    openrouter_batch_poll_s: float = Field(60.0, gt=0, allow_inf_nan=False)
    openrouter_batch_max_wait_s: float = Field(
        25 * 3600.0, gt=0, allow_inf_nan=False, description="Give up waiting on one batch."
    )
    openrouter_batch_providers: tuple[str, ...] = ("deepinfra", "fireworks", "together", "parasail")
    openrouter_batch_max_tokens: int | None = Field(
        None,
        ge=256,
        le=131_072,
        description=(
            "Output cap for batch bodies; lowers the pre-submit cost estimate. "
            "None reuses openrouter_max_tokens so sync and batch share cache entries."
        ),
    )

    concurrency: int = Field(4, ge=1, le=256, description="Max in-flight LLM requests.")
    request_timeout_s: float = Field(120.0, gt=0)
    max_retries: int = Field(4, ge=0, description="Retries for transient transport errors.")
    max_validation_retries: int = Field(2, ge=0, description="Retries when output fails schema.")
    retry_base_delay_s: float = Field(0.5, gt=0)

    embed_batch_size: int = Field(64, ge=1, le=512)
    cache_path: Path = Path(".society/cache.sqlite")
