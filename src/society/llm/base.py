"""Provider-agnostic interface. Everything above this layer depends only on `ChatClient`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel


@dataclass(slots=True)
class UsageMeter:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    cache_hits: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.requests += 1


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

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]: ...

    async def aclose(self) -> None: ...
