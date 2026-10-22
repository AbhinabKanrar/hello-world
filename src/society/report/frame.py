"""events.jsonl → dense per-round matrices.

The engine only writes rows for personas that changed in a round, so we forward-fill along
the round axis with a single `maximum.accumulate` — O(rounds × n), no Python loops over cells.
Memory: ~ (rounds+1) × n × 7 bytes; 100k personas × 50 rounds ≈ 35 MB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final
from collections.abc import Sequence

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
    def load(
        cls,
        sim_dir: Path,
        *,
        expected_n: int | None = None,
        expected_scenario_hash: str | None = None,
        expected_ids: Sequence[str] | None = None,
    ) -> Frame:
        manifest_path = sim_dir / "sim.manifest.json"
        manifest = SimManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )

        if not 1 <= manifest.size <= 100_000:
            raise ValueError("simulation population size is outside supported bounds")
        if not 0 <= manifest.rounds <= 52:
            raise ValueError("simulation round count is outside supported bounds")
        if expected_n is not None and manifest.size != expected_n:
            raise ValueError(
                f"simulation has {manifest.size} personas, expected {expected_n}"
            )
        if (
            expected_scenario_hash is not None
            and manifest.scenario_hash != expected_scenario_hash
        ):
            raise ValueError("report scenario does not match the simulation")

        if expected_ids is not None:
            if len(expected_ids) != manifest.size:
                raise ValueError("persona ID count does not match the simulation")
            if len(set(expected_ids)) != manifest.size:
                raise ValueError("persona IDs must be unique")

        expected_rounds = list(range(manifest.rounds + 1))
        if [stat.round for stat in manifest.per_round] != expected_rounds:
            raise ValueError("simulation manifest has incomplete or unordered rounds")

        for stat in manifest.per_round:
            if not 0 <= stat.llm_calls <= manifest.size:
                raise ValueError("invalid per-round LLM-call count")
            if not 0 <= stat.decayed <= manifest.size:
                raise ValueError("invalid per-round decay count")
            if stat.llm_calls + stat.decayed > manifest.size:
                raise ValueError("per-round update count exceeds population size")
            if not 0 <= stat.cache_hits <= stat.llm_calls:
                raise ValueError("invalid per-round cache-hit count")

        f = cls(manifest)
        seen = np.zeros((f.rounds + 1, f.n), dtype=np.bool_)
        rows_per_round = np.zeros(f.rounds + 1, dtype=np.int64)
        decays_per_round = np.zeros(f.rounds + 1, dtype=np.int64)
        previous_key = (-1, -1)
        float32_max = float(np.finfo(np.float32).max)

        for event in read_jsonl(sim_dir / "events.jsonl", SimEvent):
            rnd, index = event.round, event.index
            key = (rnd, index)

            if rnd > f.rounds or index >= f.n:
                raise ValueError(f"event out of range: round={rnd} index={index}")
            if key <= previous_key:
                raise ValueError("event rows must be unique and ordered by round/index")
            previous_key = key

            if expected_ids is not None and event.persona_id != expected_ids[index]:
                raise ValueError(f"persona ID mismatch at index {index}")
            if rnd == 0 and event.trigger != "exposure":
                raise ValueError("round 0 must contain exposure events")
            if rnd > 0 and event.trigger == "exposure":
                raise ValueError("exposure events are only valid in round 0")
            if event.max_price > float32_max:
                raise ValueError("max_price exceeds the simulation storage range")

            seen[rnd, index] = True
            rows_per_round[rnd] += 1
            decays_per_round[rnd] += int(event.trigger == "decay")

            f.interest[rnd, index] = event.interest
            f.intent[rnd, index] = event.purchase_intent
            f.max_price[rnd, index] = event.max_price
            f.share[rnd, index] = event.would_share

            if event.purchase_intent >= ADOPT_THRESHOLD and f.first_adopt[index] < 0:
                f.first_adopt[index] = rnd
                f.adopt_trigger[index] = _TRIGGER[event.trigger]
                f.adopt_peer[index] = event.peer_msgs > 0
                f.adopt_channel[index] = event.channel_msgs > 0

            f.objection[index] = event.top_objection
            f.stance[index] = event.stance
            if event.reasoning:
                f.reasoning[index] = event.reasoning

        if not seen[0].all():
            raise ValueError("round 0 is incomplete")

        for stat in manifest.per_round:
            if rows_per_round[stat.round] != stat.llm_calls + stat.decayed:
                raise ValueError(f"event count mismatch in round {stat.round}")
            if decays_per_round[stat.round] != stat.decayed:
                raise ValueError(f"decay count mismatch in round {stat.round}")

        indices = _ffill_index(seen)
        columns = np.arange(f.n)
        f.interest = f.interest[indices, columns]
        f.intent = f.intent[indices, columns]
        f.max_price = f.max_price[indices, columns]
        f.share = f.share[indices, columns]

        # Match the engine's four-decimal adoption and three-decimal interest.
        adoption = (f.intent >= ADOPT_THRESHOLD).mean(axis=1)
        interest = f.interest.mean(axis=1)

        for stat in manifest.per_round:
            if not np.isclose(
                adoption[stat.round], stat.adoption, rtol=0.0, atol=0.000051
            ):
                raise ValueError(f"adoption mismatch in round {stat.round}")
            if not np.isclose(
                interest[stat.round], stat.mean_interest, rtol=0.0, atol=0.00051
            ):
                raise ValueError(f"mean-interest mismatch in round {stat.round}")

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
