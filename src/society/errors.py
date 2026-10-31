from __future__ import annotations


class SocietyError(Exception):
    """Base class for every error raised by this package."""


class SpecError(SocietyError):
    """Invalid audience or scenario spec (YAML, schema, or semantic check)."""


class LLMError(SocietyError):
    """LLM provider failure that survived all retries."""

    def __init__(self, message: str, *, category: str = "provider_error") -> None:
        super().__init__(message)
        self.category = category


# Categories where another attempt cannot succeed without operator action.
PERMANENT_LLM_CATEGORIES: frozenset[str] = frozenset(
    {"authentication", "insufficient_credits", "invalid_request", "model_unavailable"}
)


def aggregate_llm_error(message: str, errors: list[LLMError]) -> LLMError:
    """Summarize per-item failures, surfacing a permanent category if any item had one."""
    permanent = next((e.category for e in errors if e.category in PERMANENT_LLM_CATEGORIES), None)
    return LLMError(message, category=permanent or "provider_error")


class LLMTransientError(LLMError):
    """Retryable provider failure (transport error, 408/409/425/429/5xx)."""
