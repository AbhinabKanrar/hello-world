"""events.jsonl → dense per-round matrices.

The engine only writes rows for personas that changed in a round, so we forward-fill along
the round axis with a single `maximum.accumulate` — O(rounds × n), no Python loops over cells.
Memory: ~ (rounds+1) × n × 7 bytes; 100k personas × 50 rounds ≈ 35 MB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from society.sim.schemas import SimEvent, SimManifest
from society.storage import read_jsonl

_TRIGGER: Final = {"exposure": 0, "influence": 1, "decay": 2}
ADOPT_THRESHOLD: Final = 4


def _ffill_index(seen: NDArray[np.bool_]) -> NDArray[np.int64]:
    rounds = np.arange(seen.shape[0], dtype=np.int64)[:, None]
    return np.maximum.accumulate(np.where(seen, rounds, 0), axis=0)


class Frame:
    __slots__ = (
        "adopt_channel",
        "adopt_peer",
        "adopt_trigger",
        "first_adopt",
        "intent",
        "interest",
        "manifest",
        "max_price",
        "n",
        "objection",
        "reasoning",
        "rounds",
        "share",
        "stance",
    )

    def __init__(self, manifest: SimManifest) -> None:
        self.manifest = manifest
        self.n, self.rounds = manifest.size, manifest.rounds
        shape = (self.rounds + 1, self.n)
        self.interest = np.zeros(shape, np.int8)
        self.intent = np.zeros(shape, np.int8)
        self.max_price = np.zeros(shape, np.float32)
        self.share = np.zeros(shape, np.bool_)
        self.first_adopt = np.full(self.n, -1, np.int32)
        self.adopt_trigger = np.zeros(self.n, np.int8)
        self.adopt_peer = np.zeros(self.n, np.bool_)
        self.adopt_channel = np.zeros(self.n, np.bool_)
        self.objection: list[str] = [""] * self.n
        self.reasoning: list[str] = [""] * self.n
        self.stance: list[str] = [""] * self.n

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, sim_dir: Path, *, expected_n: int | None = None) -> Frame:
        manifest = SimManifest.model_validate_json((sim_dir / "sim.manifest.json").read_text())
        if expected_n is not None and manifest.size != expected_n:
            raise ValueError(f"simulation has {manifest.size} personas, expected {expected_n}")
        f = cls(manifest)
        seen = np.zeros((f.rounds + 1, f.n), np.bool_)

        for e in read_jsonl(sim_dir / "events.jsonl", SimEvent):
            r, i = e.round, e.index
            if r > f.rounds or i >= f.n:
                raise ValueError(f"event out of range: round={r} index={i}")
            seen[r, i] = True
            f.interest[r, i] = e.interest
            f.intent[r, i] = e.purchase_intent
            f.max_price[r, i] = e.max_price
            f.share[r, i] = e.would_share
            if e.purchase_intent >= ADOPT_THRESHOLD and f.first_adopt[i] < 0:
                f.first_adopt[i] = r
                f.adopt_trigger[i] = _TRIGGER[e.trigger]
                f.adopt_peer[i] = e.peer_msgs > 0
                f.adopt_channel[i] = e.channel_msgs > 0
            f.objection[i] = e.top_objection
            f.stance[i] = e.stance
            if e.reasoning:
                f.reasoning[i] = e.reasoning

        if not seen[0].all():
            raise ValueError("round 0 is incomplete — simulation did not finish exposure")
        idx, cols = _ffill_index(seen), np.arange(f.n)
        f.interest, f.intent = f.interest[idx, cols], f.intent[idx, cols]
        f.max_price, f.share = f.max_price[idx, cols], f.share[idx, cols]
        return f

    # --------------------------------------------------------------- views
    @property
    def adopted(self) -> NDArray[np.bool_]:
        return self.intent[-1] >= ADOPT_THRESHOLD

    @property
    def cache_hit_ratio(self) -> float | None:
        calls = sum(r.llm_calls for r in self.manifest.per_round)
        hits = sum(r.cache_hits for r in self.manifest.per_round)
        return round(hits / calls, 4) if calls else None
