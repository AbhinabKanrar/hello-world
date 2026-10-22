"""OpenRouter chat with local Ollama embeddings.

Owns its HTTP client, optional cache, and lazily created embedding client.
Create one instance per CLI operation; close it after outstanding calls finish.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache

import httpx
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from society.config import Settings
from society.errors import LLMError
from society.llm.base import UsageMeter
from society.llm.cache import ResponseCache
from society.llm.ollama import OllamaClient

_log = logging.getLogger(__name__)
_BASE_URL = "https://openrouter.ai/api/v1/"
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_SCHEMA_ADAPTER = TypeAdapter(dict[str, JsonValue])
_JITTER = random.SystemRandom()


class _WireModel(BaseModel):
    """Validate consumed fields while tolerating additional API metadata."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )


class _Usage(_WireModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)


class _APIError(_WireModel):
    code: int | str
    message: str = ""


class _Message(_WireModel):
    content: str | None = None
    refusal: str | None = None


class _Choice(_WireModel):
    message: _Message
    finish_reason: str | None = None
    error: _APIError | None = None


class _Completion(_WireModel):
    id: str | None = None
    provider: str | None = None
    model: str | None = None
    choices: tuple[_Choice, ...] = ()
    usage: _Usage | None = None
    error: _APIError | None = None


class _CacheEntry(_WireModel):
    content: str
    provider: str | None = None
    response_id: str | None = None
    model: str | None = None


class _RetryableError(LLMError):
    def __init__(self, reason: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(reason)
        self.retry_after_s = retry_after_s


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None

    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None

    return max(0.0, seconds) if math.isfinite(seconds) else None


def _prepare_schema_node(value: JsonValue) -> JsonValue:
    """Prepare closed-object schemas without discarding validation constraints."""
    if not isinstance(value, dict):
        return value

    node = dict(value)
    node.pop("default", None)

    for key in ("properties", "$defs", "definitions"):
        children = node.get(key)
        if isinstance(children, dict):
            node[key] = {
                name: _prepare_schema_node(child)
                for name, child in children.items()
            }

    for key in ("items", "not", "if", "then", "else"):
        child = node.get(key)
        if isinstance(child, dict):
            node[key] = _prepare_schema_node(child)

    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        children = node.get(key)
        if isinstance(children, list):
            node[key] = [_prepare_schema_node(child) for child in children]

    if node.get("type") == "object":
        properties = node.get("properties")
        if not isinstance(properties, dict) or node.get("additionalProperties") is not False:
            raise LLMError(
                "Strict output requires closed object schemas: "
                "use extra='forbid' and explicitly declared fields."
            )
        # Require even fields that have local defaults, such as share_message.
        node["required"] = [name for name in properties]

    return node


@lru_cache(maxsize=64)
def _output_schema(schema: type[BaseModel]) -> dict[str, JsonValue]:
    raw = _SCHEMA_ADAPTER.validate_python(schema.model_json_schema())
    prepared = _prepare_schema_node(raw)
    if not isinstance(prepared, dict):
        raise LLMError("Output schema must be an object.")
    return prepared


def _error_status(error: _APIError) -> int | None:
    try:
        return int(error.code)
    except ValueError:
        return None


class OpenRouterClient:
    def __init__(self, settings: Settings, cache: ResponseCache | None = None) -> None:
        secret = settings.openrouter_api_key
        if secret is None or not secret.get_secret_value().strip():
            raise LLMError("Set SOCIETY_OPENROUTER_API_KEY before using OpenRouter.")
        if not settings.chat_model.strip() or "/" not in settings.chat_model:
            raise LLMError(
                "Set SOCIETY_CHAT_MODEL to an OpenRouter model ID, "
                "for example openai/gpt-oss-120b."
            )

        providers = settings.openrouter_providers
        if not providers or any(not p.strip() or p != p.strip() for p in providers):
            raise LLMError("Configure at least one non-empty OpenRouter provider slug.")
        if len(set(providers)) != len(providers):
            raise LLMError("OpenRouter provider slugs must be unique.")

        self._s = settings
        self._cache = cache
        self._closed = False
        self._embedder: OllamaClient | None = None
        self._sem = asyncio.Semaphore(settings.concurrency)
        self.usage = UsageMeter()

        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {secret.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.request_timeout_s, connect=10.0),
            limits=httpx.Limits(
                max_connections=settings.concurrency,
                max_keepalive_connections=settings.concurrency,
            ),
            follow_redirects=False,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise LLMError("OpenRouterClient is closed.")

    def _payload(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float,
        seed: int | None,
    ) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "model": self._s.chat_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "temperature": temperature,
            "max_tokens": self._s.openrouter_max_tokens,
            "provider": {
                "only": [p for p in self._s.openrouter_providers],
                "order": [p for p in self._s.openrouter_providers],
                "allow_fallbacks": self._s.openrouter_allow_fallbacks,
                "require_parameters": True,
            },
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "society_response",
                    "strict": True,
                    "schema": _output_schema(schema),
                },
            },
        }
        if seed is not None and self._s.openrouter_send_seed:
            payload["seed"] = seed
        if self._s.openrouter_reasoning_effort is not None:
            payload["reasoning"] = {
                "effort": self._s.openrouter_reasoning_effort,
                "exclude": True,
            }
        return payload

    def _cached[T: BaseModel](self, key: str, schema: type[T]) -> T | None:
        if self._cache is None:
            return None
        hit = self._cache.get(key)
        if hit is None:
            return None

        try:
            entry = _CacheEntry.model_validate_json(hit)
            result = schema.model_validate_json(entry.content)
        except ValidationError:
            _log.warning("openrouter_cache_invalid", extra={"cache_key": key})
            return None

        self.usage.cache_hits += 1
        _log.debug(
            "openrouter_cache_hit",
            extra={
                "cache_key": key,
                "provider": entry.provider,
                "response_id": entry.response_id,
            },
        )
        return result

    async def complete_json[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.8,
        seed: int | None = None,
    ) -> T:
        self._ensure_open()
        payload = self._payload(
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            seed=seed,
        )
        key = ResponseCache.key(
            adapter="openrouter-v1",
            base_url=_BASE_URL,
            request=payload,
            logical_seed=seed,
        )
        cached = self._cached(key, schema)
        if cached is not None:
            return cached

        # Timeout excludes waiting for a slot, but includes transport,
        # backoff, and output-correction attempts once admitted.
        async with self._sem:
            self._ensure_open()
            cached = self._cached(key, schema)
            if cached is not None:
                return cached
            try:
                async with asyncio.timeout(self._s.openrouter_call_timeout_s):
                    return await self._generate(payload, schema, key)
            except TimeoutError:
                raise LLMError("OpenRouter call exceeded its total time budget.") from None

    async def _generate[T: BaseModel](
        self,
        payload: dict[str, JsonValue],
        schema: type[T],
        cache_key: str,
    ) -> T:
        for attempt in range(self._s.max_validation_retries + 1):
            response = await self._post(payload)
            if len(response.choices) != 1:
                raise LLMError("OpenRouter returned an unexpected number of choices.")

            choice = response.choices[0]
            if choice.message.refusal or choice.finish_reason == "content_filter":
                raise LLMError("The provider declined the structured-output request.")
            if choice.finish_reason == "length":
                raise LLMError(
                    "OpenRouter output was truncated. Increase "
                    "SOCIETY_OPENROUTER_MAX_TOKENS or reduce reasoning effort."
                )
            if choice.finish_reason != "stop":
                raise LLMError("OpenRouter did not return a normally completed response.")

            content = choice.message.content
            if not content or not content.strip():
                raise LLMError("OpenRouter returned no final answer.")

            try:
                result = schema.model_validate_json(content)
            except ValidationError as exc:
                _log.warning(
                    "openrouter_schema_violation",
                    extra={"attempt": attempt, "response_id": response.id},
                )
                if attempt >= self._s.max_validation_retries:
                    raise LLMError("OpenRouter output failed schema validation.") from None

                errors = exc.errors(
                    include_input=False,
                    include_context=False,
                    include_url=False,
                )
                messages = payload.get("messages")
                if not isinstance(messages, list):
                    raise LLMError("Invalid internal message payload.") from None
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Return the complete corrected JSON object only. "
                                "Fix these validation errors:\n"
                                + json.dumps(errors, ensure_ascii=False)
                            ),
                        },
                    ]
                )
                continue

            if self._cache is not None:
                entry = _CacheEntry(
                    content=result.model_dump_json(),
                    provider=response.provider,
                    response_id=response.id,
                    model=response.model,
                )
                self._cache.put(cache_key, entry.model_dump_json())
            return result

        raise AssertionError("unreachable")

    async def _request_once(self, payload: dict[str, JsonValue]) -> _Completion:
        response = await self._http.post("chat/completions", json=payload)
        retry_after = _retry_after_seconds(response.headers.get("Retry-After"))

        if response.status_code in _RETRYABLE_STATUS:
            raise _RetryableError(
                f"HTTP {response.status_code}",
                retry_after_s=retry_after,
            )
        if not response.is_success:
            # Do not expose response bodies: they can contain submitted data.
            raise LLMError(
                f"OpenRouter HTTP {response.status_code}; "
                "check credentials, credit balance, routing, and parameter support."
            )

        try:
            completion = _Completion.model_validate_json(response.content)
        except ValidationError:
            raise _RetryableError("Malformed API response.") from None

        usage = completion.usage
        if usage is not None:
            self.usage.add(usage.prompt_tokens, usage.completion_tokens)

        _log.info(
            "openrouter_response",
            extra={
                "response_id": completion.id,
                "provider": completion.provider,
                "model": completion.model,
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
                "cost_usd": usage.cost if usage else None,
            },
        )

        error = completion.error
        if error is None:
            error = next(
                (choice.error for choice in completion.choices if choice.error is not None),
                None,
            )
        if error is not None:
            status = _error_status(error)
            if status in _RETRYABLE_STATUS:
                raise _RetryableError(
                    f"Provider error {status}",
                    retry_after_s=retry_after,
                )
            raise LLMError(
                f"OpenRouter returned an API error; response_id={completion.id!r}."
            )

        if usage is None:
            _log.warning(
                "openrouter_usage_missing",
                extra={"response_id": completion.id},
            )
        return completion

    async def _post(self, payload: dict[str, JsonValue]) -> _Completion:
        delay = min(
            self._s.retry_base_delay_s,
            self._s.openrouter_max_retry_delay_s,
        )
        for attempt in range(self._s.max_retries + 1):
            try:
                return await self._request_once(payload)
            except (httpx.TransportError, _RetryableError) as exc:
                if attempt >= self._s.max_retries:
                    raise LLMError("OpenRouter transport retries exhausted.") from None

                retry_after = (
                    exc.retry_after_s if isinstance(exc, _RetryableError) else None
                )
                limit = self._s.openrouter_max_retry_delay_s
                if retry_after is not None and retry_after > limit:
                    raise LLMError(
                        "Provider Retry-After exceeds the configured wait limit; "
                        "retry the operation later."
                    ) from None

                sleep_for = max(_JITTER.uniform(delay / 2, delay), retry_after or 0.0)
                _log.warning(
                    "openrouter_retry",
                    extra={
                        "attempt": attempt + 1,
                        "sleep_s": round(sleep_for, 3),
                        "error_type": type(exc).__name__,
                    },
                )
                await asyncio.sleep(sleep_for)
                delay = min(delay * 2, limit)

        raise AssertionError("unreachable")

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        self._ensure_open()
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        if self._embedder is None:
            # No shared cache: this client alone owns the chat cache.
            self._embedder = OllamaClient(self._s)
        return await self._embedder.embed(texts)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._http.aclose()
        finally:
            try:
                if self._embedder is not None:
                    await self._embedder.aclose()
            finally:
                if self._cache is not None:
                    self._cache.close()
