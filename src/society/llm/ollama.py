"""Ollama client: bounded concurrency, exponential backoff with jitter, schema-enforced output."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Sequence
from typing import Any

import httpx
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ValidationError

from society.config import Settings
from society.errors import LLMError, LLMTransientError
from society.llm.base import UsageMeter
from society.llm.cache import ResponseCache

_log = logging.getLogger(__name__)
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class OllamaClient:
    def __init__(self, settings: Settings, cache: ResponseCache | None = None) -> None:
        self._s = settings
        self._cache = cache
        self._sem = asyncio.Semaphore(settings.concurrency)
        self._http = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.request_timeout_s, connect=10.0),
            limits=httpx.Limits(max_connections=settings.concurrency * 2),
        )
        self.usage = UsageMeter()

    # ----------------------------------------------------------------- chat
    async def complete_json[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.8,
        seed: int | None = None,
    ) -> T:
        json_schema = schema.model_json_schema()
        cache_key = ResponseCache.key(
            provider="ollama",
            model=self._s.chat_model,
            system=system,
            user=user,
            schema=json_schema,
            temperature=temperature,
            seed=seed,
        )
        if self._cache and (hit := self._cache.get(cache_key)) is not None:
            self.usage.cache_hits += 1
            return schema.model_validate_json(hit)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        options: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed

        last_err: Exception | None = None
        for attempt in range(self._s.max_validation_retries + 1):
            payload = {
                "model": self._s.chat_model,
                "messages": messages,
                "stream": False,
                "format": json_schema,
                "options": options,
            }
            raw = await self._post("/api/chat", payload)
            content: str = raw["message"]["content"]
            self.usage.add(int(raw.get("prompt_eval_count", 0)), int(raw.get("eval_count", 0)))
            try:
                obj = schema.model_validate_json(content)
            except ValidationError as exc:
                last_err = exc
                _log.warning("schema_violation", extra={"attempt": attempt, "errors": exc.errors()})
                # Feed the error back; small models fix themselves on the next turn.
                messages += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"Invalid. Fix these errors and return JSON only:\n{exc}",
                    },
                ]
                continue
            if self._cache:
                self._cache.put(cache_key, obj.model_dump_json())
            return obj
        raise LLMError("output failed schema validation after retries") from last_err

    # ----------------------------------------------------------- embeddings
    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        batches = [
            list(texts[i : i + self._s.embed_batch_size])
            for i in range(0, len(texts), self._s.embed_batch_size)
        ]
        results = await asyncio.gather(
            *(self._post("/api/embed", {"model": self._s.embed_model, "input": b}) for b in batches)
        )
        return np.concatenate([np.asarray(r["embeddings"], dtype=np.float32) for r in results])

    # ------------------------------------------------------------ transport
    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        delay = self._s.retry_base_delay_s
        for attempt in range(self._s.max_retries + 1):
            try:
                async with self._sem:
                    resp = await self._http.post(path, json=payload)
                if resp.status_code in _RETRYABLE_STATUS:
                    raise LLMTransientError(f"{path} -> HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
            except (httpx.TransportError, LLMTransientError, json.JSONDecodeError) as exc:
                if attempt >= self._s.max_retries:
                    raise LLMError(f"{path} failed after {attempt + 1} attempts: {exc}") from exc
                sleep_for = delay * (1 + random.random() * 0.25)  # noqa: S311 - jitter, not crypto
                _log.warning(
                    "retrying", extra={"path": path, "attempt": attempt, "sleep": sleep_for}
                )
                await asyncio.sleep(sleep_for)
                delay *= 2
            except httpx.HTTPStatusError as exc:
                raise LLMError(
                    f"{path} -> HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                ) from exc
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self._http.aclose()
        if self._cache:
            self._cache.close()
