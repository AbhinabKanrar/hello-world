"""In-memory CSR social graph + streaming persistence."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from society.graph.schemas import AdjacencyRow, Channel
from society.storage import read_jsonl, write_jsonl

_GRAPH_FILE = "graph.jsonl"
_CHANNELS_FILE = "channels.json"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "unknown"


@dataclass(frozen=True, slots=True)
class SocialGraph:
    """Directed, weighted: edge (i → j) means *i listens to j* with trust `weights`."""

    n: int
    indptr: NDArray[np.int64]  # shape (n+1,)
    indices: NDArray[np.int32]  # shape (edges,)
    weights: NDArray[np.float32]  # shape (edges,)
    channels: tuple[Channel, ...]
    memberships: tuple[tuple[str, ...], ...]  # per persona → channel ids

    # ------------------------------------------------------------ queries
    @property
    def edges(self) -> int:
        return int(self.indices.size)

    def listens_to(self, i: int) -> tuple[NDArray[np.int32], NDArray[np.float32]]:
        lo, hi = self.indptr[i], self.indptr[i + 1]
        return self.indices[lo:hi], self.weights[lo:hi]

    def out_degrees(self) -> NDArray[np.int64]:
        return np.diff(self.indptr)

    def in_degrees(self) -> NDArray[np.int64]:
        return np.bincount(self.indices, minlength=self.n).astype(np.int64)

    def channel_members(self) -> dict[str, NDArray[np.int64]]:
        return {c.id: np.asarray(c.members, dtype=np.int64) for c in self.channels}

    # ------------------------------------------------------- serialization
    def rows(self) -> Iterator[AdjacencyRow]:
        for i in range(self.n):
            nbrs, w = self.listens_to(i)
            yield AdjacencyRow(
                i=i, to=nbrs.tolist(), w=np.round(w, 4).tolist(), ch=list(self.memberships[i])
            )

    @classmethod
    def from_rows(cls, rows: Iterable[AdjacencyRow], channels: Iterable[Channel]) -> SocialGraph:
        idx: list[list[int]] = []
        wts: list[list[float]] = []
        mem: list[tuple[str, ...]] = []
        for r in rows:
            if r.i != len(idx):
                raise ValueError(f"rows must be contiguous; got {r.i} at position {len(idx)}")
            idx.append(r.to)
            wts.append(r.w)
            mem.append(tuple(r.ch))
        counts = np.fromiter((len(x) for x in idx), dtype=np.int64, count=len(idx))
        indptr = np.zeros(len(idx) + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        return cls(
            n=len(idx),
            indptr=indptr,
            indices=np.fromiter(
                (j for x in idx for j in x), dtype=np.int32, count=int(counts.sum())
            ),
            weights=np.fromiter(
                (w for x in wts for w in x), dtype=np.float32, count=int(counts.sum())
            ),
            channels=tuple(channels),
            memberships=tuple(mem),
        )

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        write_jsonl(directory / _GRAPH_FILE, self.rows())
        (directory / _CHANNELS_FILE).write_text(
            json.dumps([c.model_dump() for c in self.channels], separators=(",", ":"))
        )

    @classmethod
    def load(cls, directory: Path) -> SocialGraph:
        raw = json.loads((directory / _CHANNELS_FILE).read_text())
        channels = [Channel.model_validate(c) for c in raw]
        return cls.from_rows(read_jsonl(directory / _GRAPH_FILE, AdjacencyRow), channels)
