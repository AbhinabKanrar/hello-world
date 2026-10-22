"""Layer 1C — detect near-duplicate personas with blockwise cosine similarity.

Memory is O(block x n) instead of O(n²); n = 100k still fits comfortably.
Keeps the earliest persona in each duplicate cluster so results are stable.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from society.llm.base import ChatClient
from society.schemas import Diversity, Persona

_THRESHOLD = {Diversity.LOW: 0.97, Diversity.MEDIUM: 0.94, Diversity.HIGH: 0.90}


def find_near_duplicates(
    embeddings: NDArray[np.float32], threshold: float, *, block: int = 1024
) -> list[int]:
    n = embeddings.shape[0]
    if n < 2:
        return []
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / np.maximum(norms, 1e-12)
    flagged = np.zeros(n, dtype=bool)

    for start in range(0, n, block):
        stop = min(start + block, n)
        sims = unit[start:stop] @ unit[:stop].T  # only need j < i → upper bound at `stop`
        for k in range(stop - start):
            i = start + k
            earlier = sims[k, :i]
            # Duplicate iff similar to any *kept* earlier persona.
            hits = (earlier >= threshold) & ~flagged[:i]
            if hits.any():
                flagged[i] = True
    return np.flatnonzero(flagged).tolist()


class DiversityFilter:
    __slots__ = ("_client", "_threshold")

    def __init__(self, client: ChatClient, diversity: Diversity) -> None:
        self._client = client
        self._threshold = _THRESHOLD[diversity]

    async def duplicates(self, personas: Sequence[Persona]) -> list[int]:
        # texts = [p.profile.bio if p.profile else "" for p in personas]
        # emb = await self._client.embed(texts)
        # return find_near_duplicates(emb, self._threshold)

        idx = [i for i, p in enumerate(personas) if p.profile is not None]

        if len(idx) < 2:
            return []

        emb = await self._client.embed([personas[i].profile.bio for i in idx])  # type: ignore[union-attr]
        local = find_near_duplicates(emb, self._threshold)
        return [idx[k] for k in local]
