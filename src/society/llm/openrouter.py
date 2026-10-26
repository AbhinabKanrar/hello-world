"""OpenRouter chat, embeddings, and Batch API.

Owns its HTTP client, optional cache.
Create one instance per CLI operation; close it after outstanding calls finish.

Batch path (`complete_json_many`): requests are chunked by count and serialized bytes,
streamed to POST /batches with an exact Content-Length, polled to a final status, matched
back by custom_id, validated, cached, and yielded strictly in input order. Items the batch
could not answer fall back to the synchronous correction loop. Cache keys cover only the
per-request body, so sync and batch runs share entries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from itertools import chain, islice
from typing import cast

import httpx
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from society.config import Settings
from society.errors import LLMError
from society.llm.base import JsonRequest, UsageMeter, fan_out_json
from society.llm.cache import ResponseCache

_log = logging.getLogger(__name__)
_BASE_URL = "https://openrouter.ai/api/v1/"
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_SCHEMA_ADAPTER = TypeAdapter(dict[str, JsonValue])
_JITTER = random.SystemRandom()
_CACHE_ADAPTER = "openrouter-v2"
_BATCH_ENDPOINT = "/v1/chat/completions"
_BATCH_FINAL = frozenset({"completed", "failed", "expired", "cancelled"})
_BATCH_FIRST_POLL_S = 15.0
_ERROR_MESSAGE_LIMIT = 200


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


class _EmbeddingItem(_WireModel):
    index: int = Field(ge=0)
    embedding: list[float] = Field(min_length=1)


class _EmbeddingUsage(_WireModel):
    prompt_tokens: int = Field(ge=0)


class _EmbeddingResponse(_WireModel):
    model: str
    data: list[_EmbeddingItem] = Field(min_length=1)
    usage: _EmbeddingUsage | None = None


class _BatchItemError(_WireModel):
    type: str | None = None
    message: str = ""


class _BatchItemResponse(_WireModel):
    status_code: int
    body: _Completion | None = None


class _BatchResult(_WireModel):
    custom_id: str
    response: _BatchItemResponse | None = None
    error: _BatchItemError | None = None


class _BatchCounts(_WireModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)


class _BatchUsage(_WireModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)


class _Batch(_WireModel):
    id: str
    status: str
    provider: str | None = None
    request_counts: _BatchCounts | None = None
    usage: _BatchUsage | None = None
    results: list[_BatchResult] | None = None
    error: _APIError | None = None


class _ErrorEnvelope(_WireModel):
    error: _APIError | None = None


class _RetryableError(LLMError):
    def __init__(self, reason: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(reason)
        self.retry_after_s = retry_after_s


class _BatchTooLargeError(LLMError):
    """HTTP 413: the chunk exceeds the per-batch request or byte limit."""


@dataclass(slots=True)
class _Chunk:
    """A contiguous input range. Cache hits are resolved up front; `pending` go to a batch."""

    start: int
    items: list[JsonRequest | None] = field(default_factory=list)
    keys: list[str | None] = field(default_factory=list)
    results: list[BaseModel | LLMError | None] = field(default_factory=list)
    pending: list[int] = field(default_factory=list)
    bodies: list[bytes] = field(default_factory=list)
    task: asyncio.Task[None] | None = None

    @property
    def size(self) -> int:
        return len(self.results)

    def add_cached(self, key: str, result: BaseModel) -> None:
        self.items.append(None)
        self.keys.append(key)
        self.results.append(result)

    def add_pending(self, item: JsonRequest, key: str, body: bytes) -> None:
        self.pending.append(len(self.results))
        self.items.append(item)
        self.keys.append(key)
        self.results.append(None)
        self.bodies.append(body)


def _api_message(content: bytes) -> str:
    """API-supplied error text only; never echo request or generation content."""
    try:
        envelope = _ErrorEnvelope.model_validate_json(content)
    except ValidationError:
        return ""
    return envelope.error.message[:_ERROR_MESSAGE_LIMIT] if envelope.error else ""


def _final_content(completion: _Completion) -> str:
    """Shared acceptance rules for a chat completion from either the sync or batch path."""
    if completion.error is not None:
        raise LLMError("OpenRouter returned an API error inside the completion.")
    if len(completion.choices) != 1:
        raise LLMError("OpenRouter returned an unexpected number of choices.")
    choice = completion.choices[0]
    if choice.error is not None:
        raise LLMError("OpenRouter returned a choice-level error.")
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
    return content


def _dumps(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _item_prefix(custom_id: int) -> bytes:
    return b'{"custom_id":"%d","body":' % custom_id


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

        for name, providers in (
            ("SOCIETY_OPENROUTER_PROVIDERS", settings.openrouter_providers),
            ("SOCIETY_OPENROUTER_BATCH_PROVIDERS", settings.openrouter_batch_providers),
        ):
            if not providers or any(not p.strip() or p != p.strip() for p in providers):
                raise LLMError(f"{name} needs at least one non-empty provider slug.")
            if len(set(providers)) != len(providers):
                raise LLMError(f"{name} slugs must be unique.")

        self._s = settings
        self._cache = cache
        self._closed = False
        self._sem = asyncio.Semaphore(settings.concurrency)
        # Lowered at runtime when the API answers 413 with a smaller per-batch limit.
        self._batch_cap = settings.openrouter_batch_max_requests
        self.usage = UsageMeter()
        self.embedding_usage = UsageMeter()

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

    def _body(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float,
        seed: int | None,
        max_tokens: int | None = None,
    ) -> dict[str, JsonValue]:
        """Provider-independent request body: identical for sync and batch, so cacheable."""
        body: dict[str, JsonValue] = {
            "model": self._s.chat_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or self._s.openrouter_max_tokens,
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
            body["seed"] = seed
        if self._s.openrouter_reasoning_effort is not None:
            body["reasoning"] = {
                "effort": self._s.openrouter_reasoning_effort,
                "exclude": True,
            }
        return body

    def _payload(self, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Sync chat/completions payload: body plus routing preferences."""
        return {
            **body,
            "stream": False,
            "provider": {
                "only": list(self._s.openrouter_providers),
                "order": list(self._s.openrouter_providers),
                "allow_fallbacks": self._s.openrouter_allow_fallbacks,
                "require_parameters": True,
            },
        }

    @staticmethod
    def _cache_key(body: dict[str, JsonValue], seed: int | None) -> str:
        return ResponseCache.key(
            adapter=_CACHE_ADAPTER,
            base_url=_BASE_URL,
            request=body,
            logical_seed=seed,
        )

    def _store(
        self,
        key: str,
        result: BaseModel,
        *,
        provider: str | None,
        response_id: str | None,
        model: str | None,
    ) -> None:
        if self._cache is None:
            return
        entry = _CacheEntry(
            content=result.model_dump_json(),
            provider=provider,
            response_id=response_id,
            model=model,
        )
        self._cache.put(key, entry.model_dump_json())

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
        body = self._body(
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            seed=seed,
        )
        key = self._cache_key(body, seed)
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
                    return await self._generate(self._payload(body), schema, key)
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
            content = _final_content(response)

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

            self._store(
                cache_key,
                result,
                provider=response.provider,
                response_id=response.id,
                model=response.model,
            )
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

    # ------------------------------------------------------------------ batch
    async def complete_json_many[T: BaseModel](
        self,
        requests: Iterable[JsonRequest],
        *,
        schema: type[T],
        temperature: float = 0.8,
    ) -> AsyncIterator[tuple[int, T | LLMError]]:
        """Yield `(position, result)` in input order. Small inputs use the sync path."""
        self._ensure_open()
        s = self._s
        it = iter(requests)
        head = list(islice(it, s.openrouter_batch_min_requests))
        stream = chain(head, it)

        if not s.openrouter_batch_enabled or len(head) < s.openrouter_batch_min_requests:
            async for item in fan_out_json(
                self, stream, schema=schema, temperature=temperature, concurrency=s.concurrency
            ):
                yield item
            return

        in_flight = asyncio.Semaphore(s.openrouter_batch_max_in_flight)
        # Bounded so an all-cached input cannot materialize every chunk at once.
        queue: asyncio.Queue[_Chunk | Exception | None] = asyncio.Queue(
            maxsize=s.openrouter_batch_max_in_flight + 1
        )
        tasks: set[asyncio.Task[None]] = set()

        async def produce() -> None:
            try:
                for chunk in self._chunks(stream, schema, temperature):
                    if chunk.pending:
                        await in_flight.acquire()
                        chunk.task = asyncio.create_task(
                            self._run_chunk(chunk, schema, temperature, in_flight)
                        )
                        tasks.add(chunk.task)
                        chunk.task.add_done_callback(tasks.discard)
                    await queue.put(chunk)
                    await asyncio.sleep(0)  # let pollers run between large serializations
            except Exception as exc:
                await queue.put(exc)
            else:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    return
                if isinstance(chunk, Exception):
                    raise chunk
                if chunk.task is not None:
                    await chunk.task
                for offset, result in enumerate(chunk.results):
                    if result is None:
                        raise RuntimeError("batch chunk left a result slot unfilled")
                    yield chunk.start + offset, cast("T | LLMError", result)
                chunk.results = []
        finally:
            producer.cancel()
            for task in tasks:
                task.cancel()
            await asyncio.gather(producer, *tasks, return_exceptions=True)

    def _chunks(
        self,
        requests: Iterable[JsonRequest],
        schema: type[BaseModel],
        temperature: float,
    ) -> Iterator[_Chunk]:
        """Contiguous ranges bounded by request count and serialized bytes; cache hits are free."""
        max_bytes = self._s.openrouter_batch_max_bytes
        chunk: _Chunk | None = None
        nbytes = 0

        for position, request in enumerate(requests):
            body = self._body(
                system=request.system,
                user=request.user,
                schema=schema,
                temperature=temperature,
                seed=request.seed,
                max_tokens=self._s.openrouter_batch_max_tokens,
            )
            key = self._cache_key(body, request.seed)
            cached = self._cached(key, schema)
            encoded = None if cached is not None else _dumps(body)
            item_bytes = 0 if encoded is None else len(encoded) + len(_item_prefix(position)) + 2

            if chunk is not None and (
                chunk.size >= self._batch_cap
                or (encoded is not None and chunk.pending and nbytes + item_bytes > max_bytes)
            ):
                yield chunk
                chunk = None
            if chunk is None:
                chunk = _Chunk(start=position)
                nbytes = 0

            if cached is not None:
                chunk.add_cached(key, cached)
            else:
                assert encoded is not None
                chunk.add_pending(request, key, encoded)
                nbytes += item_bytes

        if chunk is not None:
            yield chunk

    async def _run_chunk(
        self,
        chunk: _Chunk,
        schema: type[BaseModel],
        temperature: float,
        in_flight: asyncio.Semaphore,
    ) -> None:
        """Submit, wait, collect, fall back, release. Fills every `chunk.results` slot."""
        try:
            groups: list[tuple[list[int], list[bytes]]] = [
                ([chunk.start + o for o in chunk.pending], chunk.bodies)
            ]
            chunk.bodies = []
            submitted: list[tuple[list[int], _Batch]] = []
            while groups:
                ids, bodies = groups.pop()
                try:
                    submitted.append((ids, await self._submit_batch(ids, bodies)))
                except _BatchTooLargeError:
                    if len(ids) == 1:
                        raise LLMError("A single batch request exceeds the API size limit.") from None
                    mid = len(ids) // 2
                    self._batch_cap = max(1, min(self._batch_cap, mid))
                    _log.warning("openrouter_batch_split", extra={"new_cap": self._batch_cap})
                    groups.append((ids[:mid], bodies[:mid]))
                    groups.append((ids[mid:], bodies[mid:]))

            finals = await asyncio.gather(
                *(self._await_batch(batch.id) for _, batch in submitted)
            )
            fallback: list[int] = []
            for (ids, _), final in zip(submitted, finals, strict=True):
                fallback.extend(self._collect(chunk, ids, final, schema))
                await self._delete_batch(final.id)

            if fallback:
                _log.info(
                    "openrouter_batch_fallback",
                    extra={"chunk_start": chunk.start, "count": len(fallback)},
                )
                await asyncio.gather(
                    *(self._fallback(chunk, offset, schema, temperature) for offset in fallback)
                )
        finally:
            in_flight.release()

    async def _fallback(
        self, chunk: _Chunk, offset: int, schema: type[BaseModel], temperature: float
    ) -> None:
        item = chunk.items[offset]
        if item is None:
            raise RuntimeError("fallback requested for a cached item")
        try:
            chunk.results[offset] = await self.complete_json(
                system=item.system,
                user=item.user,
                schema=schema,
                temperature=temperature,
                seed=item.seed,
            )
        except LLMError as exc:
            chunk.results[offset] = exc

    def _batch_head(self) -> bytes:
        # Field order matters: the API streams the body and requires `requests` last.
        head = {
            "endpoint": _BATCH_ENDPOINT,
            "model": self._s.chat_model,
            "provider": {
                "only": list(self._s.openrouter_batch_providers),
                "allow_fallbacks": self._s.openrouter_allow_fallbacks,
            },
            "completion_window": "24h",
        }
        return _dumps(head)[:-1] + b',"requests":['

    async def _submit_batch(self, ids: Sequence[int], bodies: Sequence[bytes]) -> _Batch:
        head = self._batch_head()
        length = (
            len(head)
            + sum(len(_item_prefix(i)) + len(b) + 1 for i, b in zip(ids, bodies, strict=True))
            + max(len(ids) - 1, 0)
            + 2
        )

        async def content() -> AsyncIterator[bytes]:
            yield head
            for n, (i, b) in enumerate(zip(ids, bodies, strict=True)):
                yield (b"," if n else b"") + _item_prefix(i) + b + b"}"
            yield b"]}"

        s = self._s
        timeout = httpx.Timeout(s.request_timeout_s, connect=10.0, write=s.openrouter_call_timeout_s)
        delay = min(s.retry_base_delay_s, s.openrouter_max_retry_delay_s)
        for attempt in range(s.max_retries + 1):
            try:
                response = await self._http.post(
                    "batches",
                    content=content(),
                    headers={"Content-Length": str(length)},
                    timeout=timeout,
                )
            except httpx.TransportError as exc:
                if attempt >= s.max_retries:
                    raise LLMError("OpenRouter batch submit retries exhausted.") from None
                sleep_for = _JITTER.uniform(delay / 2, delay)
                _log.warning(
                    "openrouter_batch_submit_retry",
                    extra={"attempt": attempt + 1, "error_type": type(exc).__name__},
                )
                await asyncio.sleep(sleep_for)
                delay = min(delay * 2, s.openrouter_max_retry_delay_s)
                continue

            code = response.status_code
            if code == 413:
                raise _BatchTooLargeError(_api_message(response.content))
            if code == 402:
                raise LLMError(
                    "OpenRouter rejected the batch: estimated cost exceeds the credit balance. "
                    "Add credits or lower SOCIETY_OPENROUTER_BATCH_MAX_REQUESTS."
                )
            if code in _RETRYABLE_STATUS:
                if attempt >= s.max_retries:
                    raise LLMError(f"OpenRouter batch submit HTTP {code} after retries.")
                retry_after = _retry_after_seconds(response.headers.get("Retry-After")) or 0.0
                # 429 here means too many batches in progress: wait a poll interval, not ms.
                floor = s.openrouter_batch_poll_s if code == 429 else delay
                sleep_for = max(retry_after, floor)
                _log.warning(
                    "openrouter_batch_submit_retry",
                    extra={"attempt": attempt + 1, "status": code, "sleep_s": round(sleep_for, 1)},
                )
                await asyncio.sleep(sleep_for)
                delay = min(delay * 2, s.openrouter_max_retry_delay_s)
                continue
            if not response.is_success:
                raise LLMError(
                    f"OpenRouter batch submit HTTP {code}: {_api_message(response.content)}"
                )
            try:
                batch = _Batch.model_validate_json(response.content)
            except ValidationError:
                raise LLMError("OpenRouter returned a malformed batch acknowledgement.") from None
            _log.info(
                "openrouter_batch_submitted",
                extra={
                    "batch_id": batch.id,
                    "provider": batch.provider,
                    "requests": len(ids),
                    "bytes": length,
                },
            )
            return batch

        raise AssertionError("unreachable")

    async def _await_batch(self, batch_id: str) -> _Batch:
        """Poll until a final status with results present. Timeout leaves the batch running."""
        s = self._s
        loop = asyncio.get_running_loop()
        deadline = loop.time() + s.openrouter_batch_max_wait_s
        delay = min(_BATCH_FIRST_POLL_S, s.openrouter_batch_poll_s)
        consecutive_errors = 0

        while True:
            await asyncio.sleep(delay)
            delay = s.openrouter_batch_poll_s
            try:
                response = await self._http.get(f"batches/{batch_id}")
            except httpx.TransportError:
                consecutive_errors += 1
                if consecutive_errors > s.max_retries:
                    raise LLMError(f"Lost contact while polling batch {batch_id}.") from None
                continue

            code = response.status_code
            if code == 429:
                delay = s.openrouter_batch_poll_s * 2
                continue
            if code >= 500:
                consecutive_errors += 1
                if consecutive_errors > s.max_retries:
                    raise LLMError(f"OpenRouter kept failing while polling batch {batch_id}.")
                continue
            if not response.is_success:
                raise LLMError(
                    f"OpenRouter batch {batch_id} poll HTTP {code}: "
                    f"{_api_message(response.content)}"
                )
            consecutive_errors = 0

            try:
                batch = _Batch.model_validate_json(response.content)
            except ValidationError:
                raise LLMError(f"OpenRouter returned a malformed batch {batch_id}.") from None

            if batch.status in _BATCH_FINAL and (
                batch.status != "completed" or batch.results is not None
            ):
                return batch
            if loop.time() >= deadline:
                raise LLMError(
                    f"Batch {batch_id} did not finish within the wait limit; "
                    "it continues server-side and results stay readable for 30 days."
                )

    def _collect(
        self,
        chunk: _Chunk,
        ids: Sequence[int],
        batch: _Batch,
        schema: type[BaseModel],
    ) -> list[int]:
        """Fill result slots from one final batch; return offsets needing the sync fallback."""
        counts = batch.request_counts
        _log.info(
            "openrouter_batch_final",
            extra={
                "batch_id": batch.id,
                "status": batch.status,
                "provider": batch.provider,
                "total": counts.total if counts else None,
                "completed": counts.completed if counts else None,
                "failed": counts.failed if counts else None,
                "prompt_tokens": batch.usage.prompt_tokens if batch.usage else None,
                "completion_tokens": batch.usage.completion_tokens if batch.usage else None,
                "cost_usd": batch.usage.cost if batch.usage else None,
            },
        )
        if batch.status != "completed" or batch.results is None:
            reason = batch.error.message[:_ERROR_MESSAGE_LIMIT] if batch.error else ""
            error = LLMError(f"OpenRouter batch {batch.id} ended {batch.status}: {reason}")
            for position in ids:
                chunk.results[position - chunk.start] = error
            return []

        if batch.usage is not None:
            self.usage.add(
                batch.usage.prompt_tokens,
                batch.usage.completion_tokens,
                requests=counts.completed if counts else len(batch.results),
            )

        expected = set(ids)
        fallback: list[int] = []
        for result in batch.results:
            try:
                position = int(result.custom_id)
            except ValueError:
                continue
            if position not in expected:
                continue
            expected.discard(position)
            offset = position - chunk.start
            response = result.response
            if result.error is not None or response is None or response.body is None:
                fallback.append(offset)
                continue
            try:
                parsed = schema.model_validate_json(_final_content(response.body))
            except (LLMError, ValidationError):
                fallback.append(offset)
                continue
            key = chunk.keys[offset]
            if key is not None:
                self._store(
                    key,
                    parsed,
                    provider=batch.provider,
                    response_id=response.body.id,
                    model=response.body.model,
                )
            chunk.results[offset] = parsed

        # Results the API never returned are retried individually rather than dropped.
        fallback.extend(position - chunk.start for position in expected)
        return fallback

    async def _delete_batch(self, batch_id: str) -> None:
        """Best effort: results are already in memory, and the API expires them anyway."""
        try:
            response = await self._http.delete(f"batches/{batch_id}")
        except httpx.TransportError as exc:
            _log.warning(
                "openrouter_batch_delete_failed",
                extra={"batch_id": batch_id, "error_type": type(exc).__name__},
            )
            return
        if not response.is_success:
            _log.warning(
                "openrouter_batch_delete_failed",
                extra={"batch_id": batch_id, "status": response.status_code},
            )

    # ------------------------------------------------------------- embeddings
    @staticmethod
    def _embedding_matrix(
        response: _EmbeddingResponse,
        expected_count: int,
    ) -> NDArray[np.float32]:
        items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(expected_count)):
            raise LLMError("Embedding response has missing or duplicate indices.")

        dimension = len(items[0].embedding)
        if any(len(item.embedding) != dimension for item in items):
            raise LLMError("Embedding response contains inconsistent dimensions.")

        # Validate before converting to the float32 representation used downstream.
        matrix64 = np.asarray(
            [item.embedding for item in items],
            dtype=np.float64,
        )
        if not np.isfinite(matrix64).all():
            raise LLMError("Embedding response contains non-finite values.")
        if np.any(np.abs(matrix64) > np.finfo(np.float32).max):
            raise LLMError("Embedding values exceed float32 storage limits.")

        matrix = matrix64.astype(np.float32)
        if np.any(np.linalg.norm(matrix.astype(np.float64), axis=1) == 0):
            raise LLMError("Embedding response contains a zero vector.")
        return matrix

    async def _embedding_request(
        self,
        payload: dict[str, JsonValue],
    ) -> _EmbeddingResponse:
        """Transport retries only; invalid embedding payloads fail explicitly."""
        delay = min(
            self._s.retry_base_delay_s,
            self._s.openrouter_max_retry_delay_s,
        )

        for attempt in range(self._s.max_retries + 1):
            try:
                response = await self._http.post("embeddings", json=payload)

                if response.status_code in _RETRYABLE_STATUS:
                    raise _RetryableError(
                        f"Embedding HTTP {response.status_code}",
                        retry_after_s=_retry_after_seconds(
                            response.headers.get("Retry-After")
                        ),
                    )
                if not response.is_success:
                    raise LLMError(
                        f"OpenRouter embeddings HTTP {response.status_code}; "
                        "check embedding model, credentials, balance, and input limits."
                    )

                try:
                    parsed = _EmbeddingResponse.model_validate_json(response.content)
                except ValidationError:
                    # Do not automatically repeat potentially billable responses.
                    raise LLMError(
                        "OpenRouter returned an invalid embedding response."
                    ) from None

                if parsed.usage is not None:
                    self.embedding_usage.add(parsed.usage.prompt_tokens, 0)
                else:
                    self.embedding_usage.requests += 1
                    _log.warning("openrouter_embedding_usage_missing")

                _log.info(
                    "openrouter_embedding_response",
                    extra={
                        "model": parsed.model,
                        "count": len(parsed.data),
                        "prompt_tokens": (
                            parsed.usage.prompt_tokens if parsed.usage else None
                        ),
                    },
                )
                return parsed

            except (httpx.TransportError, _RetryableError) as exc:
                if attempt >= self._s.max_retries:
                    raise LLMError(
                        "OpenRouter embedding retries exhausted."
                    ) from None

                retry_after = (
                    exc.retry_after_s
                    if isinstance(exc, _RetryableError)
                    else None
                )
                limit = self._s.openrouter_max_retry_delay_s
                if retry_after is not None and retry_after > limit:
                    raise LLMError(
                        "Embedding Retry-After exceeds the configured wait limit."
                    ) from None

                sleep_for = max(
                    _JITTER.uniform(delay / 2, delay),
                    retry_after or 0.0,
                )
                _log.warning(
                    "openrouter_embedding_retry",
                    extra={
                        "attempt": attempt + 1,
                        "sleep_s": round(sleep_for, 3),
                        "error_type": type(exc).__name__,
                    },
                )
                await asyncio.sleep(sleep_for)
                delay = min(delay * 2, limit)

        raise AssertionError("unreachable")

    async def _embed_batch(self, texts: list[str]) -> NDArray[np.float32]:
        payload: dict[str, JsonValue] = {
            "model": self._s.embed_model,
            "input": [text for text in texts],
            "encoding_format": "float",
        }
        key = ResponseCache.key(
            adapter="openrouter-embeddings-v1",
            base_url=_BASE_URL,
            request=payload,
        )

        async with self._sem:
            self._ensure_open()

            if self._cache is not None:
                hit = self._cache.get(key)
                if hit is not None:
                    try:
                        cached = _EmbeddingResponse.model_validate_json(hit)
                        matrix = self._embedding_matrix(cached, len(texts))
                    except (ValidationError, LLMError):
                        _log.warning(
                            "openrouter_embedding_cache_invalid",
                            extra={"cache_key": key},
                        )
                    else:
                        self.embedding_usage.cache_hits += 1
                        return matrix

            try:
                async with asyncio.timeout(self._s.openrouter_call_timeout_s):
                    response = await self._embedding_request(payload)
            except TimeoutError:
                raise LLMError(
                    "OpenRouter embedding batch exceeded its time budget."
                ) from None

            matrix = self._embedding_matrix(response, len(texts))
            if self._cache is not None:
                self._cache.put(key, response.model_dump_json())
            return matrix

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        self._ensure_open()
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        if any(not text.strip() for text in texts):
            raise LLMError("Embedding input contains an empty or whitespace-only text.")

        batches: list[NDArray[np.float32]] = []
        dimension: int | None = None

        for start in range(0, len(texts), self._s.embed_batch_size):
            batch = list(texts[start : start + self._s.embed_batch_size])
            matrix = await self._embed_batch(batch)

            if dimension is None:
                dimension = matrix.shape[1]
            elif matrix.shape[1] != dimension:
                raise LLMError("Embedding dimensions changed between batches.")

            batches.append(matrix)

        if len(batches) == 1:
            return batches[0]
        return np.concatenate(batches, axis=0)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._http.aclose()
        finally:
            if self._cache is not None:
                self._cache.close()
