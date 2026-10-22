"""Construct the configured ChatClient without coupling pipeline stages to providers."""

from __future__ import annotations

from society.config import Settings
from society.llm.base import ChatClient
from society.llm.cache import ResponseCache
from society.llm.ollama import OllamaClient
from society.llm.openrouter import OpenRouterClient


def create_client(settings: Settings) -> ChatClient:
    cache = ResponseCache(settings.cache_path)
    try:
        if settings.provider == "openrouter":
            return OpenRouterClient(settings, cache)
        return OllamaClient(settings, cache)
    except Exception:
        # Construction failed before ownership could transfer to a client.
        cache.close()
        raise
