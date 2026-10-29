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


class LLMTransientError(LLMError):
    """Retryable provider failure (transport error, 408/409/425/429/5xx)."""
