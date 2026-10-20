from __future__ import annotations

class SocietyError(Exception):
    """Base class for all package error"""

class SpecError(SocietyError):
    """Invalid scenario spec"""

class LLMError(SocietyError):
    """LLM provider failure after retry"""

class LLMTransientError(LLMError):
    """Retryable provider failure (timeouts, 5xx)"""
