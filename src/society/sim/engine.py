"""Layer 3 orchestrator.

Round 0  : every persona is exposed (N LLM calls).
Round r>0: router computes the dirty set (new peer shares, channel posts, events) → LLM calls
           only for those; everyone else gets code-only decay. Events stream to events.jsonl
           and a checkpoint is written after every round so a crash resumes mid-run for free.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import uuid
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import Field

from society.errors import LLMError, aggregate_llm_error
from society.graph.model import SocialGraph
from society.llm.base import ChatClient, JsonRequest
from society.llm.cache import ResponseCache
from society.recovery import RecoveryJournal
from society.schemas import Persona, StrictModel
from society.sim import prompts
from society.sim.inbox import Inbox, InboxRouter
from society.sim.schemas import (
    Checkpoint,
    Reaction,
    RoundStats,
    ScenarioSpec,
    SimEvent,
    SimManifest,
    TrialRecord,
    TrialScenarioSpec,
    trial_answer_schema,
)
from society.sim.state import PopulationState
from society.storage import write_jsonl

_log = logging.getLogger(__name__)
_EVENTS = "events.jsonl"
_CKPT = "checkpoint.json"
_SEED_MIX = 0x9E3779B1


def _call_seed(seed: int, index: int, rnd: int) -> int:
    return (seed * _SEED_MIX + index * 7919 + rnd * 15_485_863) & 0x7FFF_FFFF


@dataclass(frozen=True, slots=True)
class SimulationResult:
    manifest: SimManifest
    events_path: Path


class SimulationProgress(StrictModel):
    checkpoint: Checkpoint | None = None
    per_round: list[RoundStats] = Field(default_factory=list)


class SimulationEngine:
    __slots__ = (
        "_cards",
        "_client",
        "_graph",
        "_model",
        "_names",
        "_out",
        "_personas",
        "_retry_from",
        "_scenario",
        "_seed",
        "_settings_hash",
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
        retry_from: Path | None = None,
        settings_hash: str = "",
    ) -> None:
        if graph.n != len(personas):
            raise ValueError(f"graph has {graph.n} nodes but {len(personas)} personas given")
        if not personas or any(p.index != i for i, p in enumerate(personas)):
            raise ValueError("personas must be nonempty with ordered, contiguous indices")
        if len({p.id for p in personas}) != len(personas):
            raise ValueError("persona IDs must be unique")
        self._client = client
        self._personas = personas
        self._graph = graph
        self._scenario = scenario
        self._seed = seed
        self._out = out_dir
        self._model = chat_model
        self._retry_from = retry_from
        self._settings_hash = settings_hash
        self._cards = [prompts.persona_card(p) for p in personas]
        self._names = [p.profile.name if p.profile else p.id for p in personas]

    # ------------------------------------------------------------------ API
    async def run(self) -> SimulationResult:
        digest = hashlib.sha256()
        for persona in self._personas:
            digest.update(persona.model_dump_json().encode())
            digest.update(b"\n")
        for array in (self._graph.indptr, self._graph.indices, self._graph.weights):
            digest.update(str(array.dtype).encode())
            digest.update(str(array.shape).encode())
            digest.update(memoryview(np.ascontiguousarray(array)))
        identity = ResponseCache.key(
            stage="simulation-recovery-v1",
            inputs=digest.hexdigest(),
            channels=[channel.model_dump(mode="json") for channel in self._graph.channels],
            memberships=self._graph.memberships,
            scenario=self._scenario.model_dump(mode="json"),
            seed=self._seed,
            model=self._model,
            settings_hash=self._settings_hash,
            response_schema=Reaction.model_json_schema(),
            levels=prompts._LEVEL,
            prompts=(
                prompts.SYSTEM,
                inspect.getsource(prompts.persona_card),
                inspect.getsource(prompts.scenario_block),
                inspect.getsource(prompts.exposure_prompt),
                inspect.getsource(prompts.update_prompt),
                inspect.getsource(prompts._trust_word),
            ),
        )
        with RecoveryJournal(self._out, identity=identity, source=self._retry_from) as journal:
            return await self._run(journal)

    async def _run(self, journal: RecoveryJournal) -> SimulationResult:
        s, n = self._scenario, len(self._personas)
        events_path, ckpt_path = self._out / _EVENTS, self._out / _CKPT
        progress = journal.state(SimulationProgress) or SimulationProgress()
        checkpoint = progress.checkpoint
        start = checkpoint.completed_round + 1 if checkpoint is not None else 0
        if [stat.round for stat in progress.per_round] != list(range(start)):
            raise ValueError("Recovery journal has incomplete or unordered round statistics")
        state = (
            PopulationState.from_checkpoint(checkpoint)
            if checkpoint is not None
            else PopulationState(n)
        )
        resumed_from = start if start > 0 else None

        influence = np.fromiter((p.traits.influence for p in self._personas), np.float32, n)
        router = InboxRouter(
            self._graph,
            influence,
            max_peer=s.max_peer_messages,
            max_channel=s.max_channel_posts,
            broadcast_top_k=s.broadcast_top_k,
        )
        stats = list(progress.per_round)

        for rnd in range(start, s.rounds + 1):
            scenario_text = prompts.scenario_block(s, price_override=s.price_at(rnd).render())
            hits_before = self._client.usage.cache_hits
            if rnd == 0:
                inboxes = {i: Inbox() for i in range(n)}
                rows = await self._query(inboxes, state, rnd, scenario_text, journal=journal)
                decayed = np.empty(0, dtype=np.int64)
            else:
                inboxes = router.route(
                    sharers=state.spoke_in(rnd - 1),
                    messages=state.share_message,
                    events=s.events_at(rnd),
                )
                rows = await self._query(inboxes, state, rnd, scenario_text, journal=journal)
                queried = np.zeros(n, dtype=np.bool_)
                queried[list(inboxes)] = True
                decayed = state.decay(rnd, every=s.decay_every, exclude=queried)
                rows += [
                    state.row(int(i), rnd, "decay", self._personas[int(i)].id) for i in decayed
                ]

            rows.sort(key=lambda e: e.index)
            rs = RoundStats(
                round=rnd,
                llm_calls=len(inboxes),
                decayed=int(decayed.size),
                cache_hits=self._client.usage.cache_hits - hits_before,
                adoption=round(state.adoption(), 4),
                mean_interest=round(state.mean_interest(), 3),
            )
            stats.append(rs)
            checkpoint = state.to_checkpoint(
                scenario_hash=s.content_hash(), seed=self._seed, completed_round=rnd
            )
            journal.advance(
                SimulationProgress(checkpoint=checkpoint, per_round=stats),
                scope=f"events:{rnd}",
                rows=((row.index, row) for row in rows),
            )
            ckpt_path.write_text(checkpoint.model_dump_json(), encoding="utf-8")
            _log.info("round_done", extra=rs.model_dump())

        write_jsonl(
            events_path,
            (
                row
                for rnd in range(s.rounds + 1)
                for _, row in journal.values(f"events:{rnd}", SimEvent)
            ),
        )
        if checkpoint is not None:
            ckpt_path.write_text(checkpoint.model_dump_json(), encoding="utf-8")
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
        (self._out / "SUCCESS").touch(exist_ok=False)
        return SimulationResult(manifest=manifest, events_path=events_path)

    # --------------------------------------------------------------- rounds
    async def _query(
        self,
        inboxes: dict[int, Inbox],
        state: PopulationState,
        rnd: int,
        scenario_text: str,
        *,
        journal: RecoveryJournal,
    ) -> list[SimEvent]:
        exposure = rnd == 0
        indices = sorted(inboxes)
        recovered = dict(journal.values(f"reactions:{rnd}", Reaction))
        if not set(recovered).issubset(inboxes):
            raise ValueError("Saved reaction is outside this round's routed population")
        pending = [i for i in indices if i not in recovered]

        def request(i: int) -> JsonRequest:
            user = (
                prompts.exposure_prompt(self._cards[i], scenario_text)
                if exposure
                else prompts.update_prompt(
                    self._cards[i], scenario_text, state.stance[i], inboxes[i], self._names
                )
            )
            return JsonRequest(
                system=prompts.SYSTEM, user=user, seed=_call_seed(self._seed, i, rnd)
            )

        rows: list[SimEvent] = []

        def apply(i: int, reaction: Reaction) -> None:
            box = inboxes[i]
            state.apply(i, reaction, rnd)
            rows.append(
                state.row(
                    i,
                    rnd,
                    "exposure" if exposure else "influence",
                    self._personas[i].id,
                    reasoning=reaction.reasoning,
                    peer=len(box.peers),
                    channel=len(box.channel),
                    events=len(box.events),
                )
            )

        for i, recovered_reaction in recovered.items():
            apply(i, recovered_reaction)
        failures: list[LLMError] = []
        received = 0
        async for position, reaction in self._client.complete_json_many(
            (request(i) for i in pending), schema=Reaction, temperature=0.7
        ):
            if position != received or position >= len(pending):
                raise ValueError("Reaction responses must be ordered and unique")
            received += 1
            i = pending[position]
            if isinstance(reaction, LLMError):
                failures.append(reaction)
                _log.warning(
                    "reaction_failed",
                    extra={"round": rnd, "persona_index": i, "failure_category": reaction.category},
                )
                continue
            journal.save(f"reactions:{rnd}", i, reaction)
            apply(i, reaction)
        if received != len(pending):
            raise LLMError("Simulation did not account for every requested reaction")
        if failures:
            raise aggregate_llm_error(
                f"{len(failures)} persona reactions failed in round {rnd}; rerun to retry.",
                failures,
            )
        return rows


async def run_trial(  # noqa: PLR0913
    client: ChatClient,
    *,
    personas: Sequence[Persona],
    audience: str,
    scenario: TrialScenarioSpec,
    seed: int,
    only: set[int] | None = None,
) -> AsyncGenerator[TrialRecord, None]:
    """Yield one record per persona in index order; handled LLM failures become records."""
    if not personas:
        raise ValueError("trial requires at least one persona")
    if any(persona.index != i for i, persona in enumerate(personas)):
        raise ValueError("personas must have ordered, contiguous indices")
    if len({persona.id for persona in personas}) != len(personas):
        raise ValueError("persona IDs must be unique")
    if only is not None and any(i < 0 or i >= len(personas) for i in only):
        raise ValueError("trial retry indices are outside the population")
    selected = [p for p in personas if only is None or p.index in only]
    if not selected:
        return

    schema = trial_answer_schema(len(scenario.options))
    requests = (
        JsonRequest(
            system=prompts.TRIAL_SYSTEM,
            user=prompts.trial_prompt(persona, audience, scenario),
            seed=_call_seed(seed, persona.index, 0),
        )
        for persona in selected
    )
    async for index, answer in client.complete_json_many(requests, schema=schema, temperature=0.7):
        persona = selected[index]
        if isinstance(answer, LLMError):
            # Do not log respondent content or provider response bodies.
            _log.warning(
                "trial_request_failed",
                extra={"persona_index": persona.index, "failure_category": answer.category},
            )
            yield TrialRecord(
                index=persona.index,
                persona_id=persona.id,
                status="technical_failure",
                answer=None,
                failure_category=answer.category,
            )
        else:
            yield TrialRecord(
                index=persona.index, persona_id=persona.id, status="answered", answer=answer
            )
