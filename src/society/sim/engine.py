"""Layer 3 orchestrator.

Round 0  : every persona is exposed (N LLM calls).
Round r>0: router computes the dirty set (new peer shares, channel posts, events) → LLM calls
           only for those; everyone else gets code-only decay. Events stream to events.jsonl
           and a checkpoint is written after every round so a crash resumes mid-run for free.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from society.graph.model import SocialGraph
from society.llm.base import ChatClient
from society.schemas import Persona
from society.sim import prompts
from society.sim.inbox import Inbox, InboxRouter
from society.sim.schemas import (
    Checkpoint,
    Reaction,
    RoundStats,
    ScenarioSpec,
    SimEvent,
    SimManifest,
)
from society.sim.state import PopulationState
from society.storage import append_jsonl

_log = logging.getLogger(__name__)
_EVENTS = "events.jsonl"
_CKPT = "checkpoint.json"
_SEED_MIX = 0x9E3779B1
_EVENT_MIN_INTEREST = 2


def _call_seed(seed: int, index: int, rnd: int) -> int:
    return (seed * _SEED_MIX + index * 7919 + rnd * 15_485_863) & 0x7FFF_FFFF


@dataclass(frozen=True, slots=True)
class SimulationResult:
    manifest: SimManifest
    events_path: Path


class SimulationEngine:
    __slots__ = (
        "_cards",
        "_client",
        "_graph",
        "_model",
        "_names",
        "_out",
        "_personas",
        "_scenario",
        "_seed",
    )

    def __init__(
        self,
        client: ChatClient,
        *,
        personas: Sequence[Persona],
        graph: SocialGraph,
        scenario: ScenarioSpec,
        seed: int,
        out_dir: Path,
        chat_model: str,
    ) -> None:
        if graph.n != len(personas):
            raise ValueError(f"graph has {graph.n} nodes but {len(personas)} personas given")
        self._client = client
        self._personas = personas
        self._graph = graph
        self._scenario = scenario
        self._seed = seed
        self._out = out_dir
        self._model = chat_model
        self._cards = [prompts.persona_card(p) for p in personas]
        self._names = [p.profile.name if p.profile else p.id for p in personas]

    # ------------------------------------------------------------------ API
    async def run(self) -> SimulationResult:
        s, n = self._scenario, len(self._personas)
        self._out.mkdir(parents=True, exist_ok=True)
        events_path, ckpt_path = self._out / _EVENTS, self._out / _CKPT

        state, start = self._resume(ckpt_path)
        if start == 0:
            events_path.unlink(missing_ok=True)
        resumed_from = start if start > 0 else None

        influence = np.fromiter((p.traits.influence for p in self._personas), np.float32, n)
        router = InboxRouter(
            self._graph,
            influence,
            max_peer=s.max_peer_messages,
            max_channel=s.max_channel_posts,
            broadcast_top_k=s.broadcast_top_k,
        )
        scenario_text = prompts.scenario_block(s)
        stats: list[RoundStats] = []

        for rnd in range(start, s.rounds + 1):
            hits_before = self._client.usage.cache_hits
            if rnd == 0:
                inboxes = {i: Inbox() for i in range(n)}
                rows = await self._query(inboxes, state, rnd, scenario_text, exposure=True)
                decayed = np.empty(0, dtype=np.int64)
            else:
                inboxes = router.route(
                    sharers=state.spoke_in(rnd - 1),
                    messages=state.share_message,
                    events=s.events_at(rnd),
                    engaged=state.interest >= _EVENT_MIN_INTEREST,
                )
                rows = await self._query(inboxes, state, rnd, scenario_text, exposure=False)
                queried = np.zeros(n, dtype=np.bool_)
                queried[list(inboxes)] = True
                decayed = state.decay(rnd, every=s.decay_every, exclude=queried)
                rows += [state.row(int(i), rnd, "decay", self._personas[i].id) for i in decayed]

            rows.sort(key=lambda e: e.index)
            append_jsonl(events_path, rows)
            ckpt_path.write_text(
                state.to_checkpoint(
                    scenario_hash=s.content_hash(), seed=self._seed, completed_round=rnd
                ).model_dump_json()
            )
            rs = RoundStats(
                round=rnd,
                llm_calls=len(inboxes),
                decayed=int(decayed.size),
                cache_hits=self._client.usage.cache_hits - hits_before,
                adoption=round(state.adoption(), 4),
                mean_interest=round(state.mean_interest(), 3),
            )
            stats.append(rs)
            _log.info("round_done", extra=rs.model_dump())

        manifest = SimManifest(
            run_id=uuid.uuid4().hex[:12],
            scenario=s.name,
            scenario_hash=s.content_hash(),
            seed=self._seed,
            size=n,
            rounds=s.rounds,
            resumed_from=resumed_from,
            chat_model=self._model,
            prompt_tokens=self._client.usage.prompt_tokens,
            completion_tokens=self._client.usage.completion_tokens,
            per_round=stats,
        )
        (self._out / "sim.manifest.json").write_text(manifest.model_dump_json(indent=2))
        return SimulationResult(manifest=manifest, events_path=events_path)

    # --------------------------------------------------------------- rounds
    async def _query(
        self,
        inboxes: dict[int, Inbox],
        state: PopulationState,
        rnd: int,
        scenario_text: str,
        *,
        exposure: bool,
    ) -> list[SimEvent]:
        rows: list[SimEvent] = []

        async def one(i: int, box: Inbox) -> None:
            user = (
                prompts.exposure_prompt(self._cards[i], scenario_text)
                if exposure
                else prompts.update_prompt(
                    self._cards[i], scenario_text, state.stance[i], box, self._names
                )
            )
            r = await self._client.complete_json(
                system=prompts.SYSTEM,
                user=user,
                schema=Reaction,
                temperature=0.7,
                seed=_call_seed(self._seed, i, rnd),
            )
            state.apply(i, r, rnd)
            rows.append(
                state.row(
                    i,
                    rnd,
                    "exposure" if exposure else "influence",
                    self._personas[i].id,
                    reasoning=r.reasoning,
                    peer=len(box.peers),
                    channel=len(box.channel),
                    events=len(box.events),
                )
            )

        async with asyncio.TaskGroup() as tg:
            for i, box in inboxes.items():
                tg.create_task(one(i, box))
        return rows

    # --------------------------------------------------------------- resume
    def _resume(self, ckpt_path: Path) -> tuple[PopulationState, int]:
        n = len(self._personas)
        if ckpt_path.exists():
            try:
                c = Checkpoint.model_validate_json(ckpt_path.read_text())
            except ValueError:
                c = None
            if (
                c
                and c.scenario_hash == self._scenario.content_hash()
                and c.seed == self._seed
                and len(c.interest) == n
            ):
                _log.info("resuming", extra={"completed_round": c.completed_round})
                return PopulationState.from_checkpoint(c), c.completed_round + 1
            _log.warning("checkpoint_ignored", extra={"reason": "scenario/seed/size mismatch"})
        return PopulationState(n), 0
