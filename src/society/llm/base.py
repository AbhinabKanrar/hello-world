"""Provider-agnostic interface. Everything above this layer depends only on `ChatClient`.

`complete_json_many` is the bulk entry point: it yields `(position, result)` strictly in
input order so callers can stream results to disk without holding the population in memory.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from society.errors import LLMError


@dataclass(slots=True)
class UsageMeter:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    cache_hits: int = 0

    def add(self, prompt: int, completion: int, *, requests: int = 1) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.requests += requests


@dataclass(frozen=True, slots=True)
class JsonRequest:
    """One structured-output request; the schema and temperature are shared per call."""

    system: str
    user: str
    seed: int | None = None


class ChatClient(Protocol):
    usage: UsageMeter

    async def complete_json[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.8,
        seed: int | None = None,
    ) -> T: ...

    def complete_json_many[T: BaseModel](
        self,
        requests: Iterable[JsonRequest],
        *,
        schema: type[T],
        temperature: float = 0.8,
    ) -> AsyncIterator[tuple[int, T | LLMError]]: ...

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]: ...

    async def aclose(self) -> None: ...


# Completed-but-unemitted results are bounded by this many per worker.
_REORDER_WINDOW_PER_WORKER = 4


async def fan_out_json[T: BaseModel](
    client: ChatClient,
    requests: Iterable[JsonRequest],
    *,
    schema: type[T],
    temperature: float,
    concurrency: int,
) -> AsyncIterator[tuple[int, T | LLMError]]:
    """Ordered fan-out over `complete_json` with bounded workers and bounded reordering.

    O(concurrency) tasks, O(concurrency) buffered results. Handled `LLMError`s are
    yielded as values; anything else propagates and cancels the remaining workers.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be positive")

    pending = iter(enumerate(requests))
    window = asyncio.Semaphore(concurrency * _REORDER_WINDOW_PER_WORKER)
    out: asyncio.Queue[tuple[int, T | LLMError] | Exception | None] = asyncio.Queue()

    async def worker() -> None:
        try:
            while True:
                await window.acquire()
                try:
                    index, request = next(pending)
                except StopIteration:
                    window.release()
                    return
                result: T | LLMError
                try:
                    result = await client.complete_json(
                        system=request.system,
                        user=request.user,
                        schema=schema,
                        temperature=temperature,
                        seed=request.seed,
                    )
                except LLMError as exc:
                    result = exc
                out.put_nowait((index, result))
        except Exception as exc:
            out.put_nowait(exc)
            raise
        finally:
            out.put_nowait(None)

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    buffered: dict[int, T | LLMError] = {}
    next_index = 0
    live = len(workers)
    try:
        while live:
            item = await out.get()
            if item is None:
                live -= 1
                continue
            if isinstance(item, Exception):
                raise item
            index, result = item
            buffered[index] = result
            while next_index in buffered:
                yield next_index, buffered.pop(next_index)
                next_index += 1
                window.release()
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
