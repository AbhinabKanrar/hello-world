"""Single-command orchestration of the four-stage simulation workflow.

Each stage is an idempotent unit: it reads durable inputs, writes artifacts into an
attempt directory, and marks completion in the study journal only after every artifact
is written. Restarting a study skips verified completed stages, resumes the failed stage
through the stage-specific ``--retry-from`` recovery, and stops on permanent errors.

The orchestrator does not reattach to provider batches that are still running
server-side; after an interruption it treats unfinished stage work as unknown and
resumes from the last durable per-item record.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Protocol

from pydantic import Field

from society.config import Settings
from society.errors import PERMANENT_LLM_CATEGORIES, LLMError, SocietyError, SpecError
from society.graph import GraphBuilder, GraphConfig, SocialGraph
from society.llm.base import ChatClient, UsageMeter
from society.llm.cache import ResponseCache
from society.llm.factory import create_client
from society.population import PopulationBuilder
from society.report import ReportBuilder
from society.schemas import AudienceSpec, Persona, StrictModel
from society.sim import ScenarioSpec, SimulationEngine
from society.storage import read_jsonl, write_jsonl

_log = logging.getLogger(__name__)

StageName = Literal["population", "graph", "simulation", "report"]
StageStatus = Literal["pending", "running", "completed", "failed", "exhausted"]
STAGES: Final[tuple[StageName, ...]] = ("population", "graph", "simulation", "report")

_JOURNAL = "study.json"
_SUCCESS = "SUCCESS"


# --------------------------------------------------------------------- state


class UsageTotals(StrictModel):
    """Observed provider usage; embedding fields are None when no meter was available."""

    chat_input_tokens: int = Field(0, ge=0)
    chat_output_tokens: int = Field(0, ge=0)
    chat_requests: int = Field(0, ge=0)
    chat_cache_hits: int = Field(0, ge=0)
    embedding_input_tokens: int | None = None
    embedding_requests: int | None = None
    embedding_cache_hits: int | None = None

    def __add__(self, other: UsageTotals) -> UsageTotals:
        def opt(a: int | None, b: int | None) -> int | None:
            return None if a is None and b is None else (a or 0) + (b or 0)

        return UsageTotals(
            chat_input_tokens=self.chat_input_tokens + other.chat_input_tokens,
            chat_output_tokens=self.chat_output_tokens + other.chat_output_tokens,
            chat_requests=self.chat_requests + other.chat_requests,
            chat_cache_hits=self.chat_cache_hits + other.chat_cache_hits,
            embedding_input_tokens=opt(self.embedding_input_tokens, other.embedding_input_tokens),
            embedding_requests=opt(self.embedding_requests, other.embedding_requests),
            embedding_cache_hits=opt(self.embedding_cache_hits, other.embedding_cache_hits),
        )

    def __sub__(self, other: UsageTotals) -> UsageTotals:
        def opt(a: int | None, b: int | None) -> int | None:
            return None if a is None else a - (b or 0)

        return UsageTotals(
            chat_input_tokens=self.chat_input_tokens - other.chat_input_tokens,
            chat_output_tokens=self.chat_output_tokens - other.chat_output_tokens,
            chat_requests=self.chat_requests - other.chat_requests,
            chat_cache_hits=self.chat_cache_hits - other.chat_cache_hits,
            embedding_input_tokens=opt(self.embedding_input_tokens, other.embedding_input_tokens),
            embedding_requests=opt(self.embedding_requests, other.embedding_requests),
            embedding_cache_hits=opt(self.embedding_cache_hits, other.embedding_cache_hits),
        )

    @classmethod
    def from_client(cls, client: ChatClient) -> UsageTotals:
        chat = client.usage
        # Only some adapters meter embeddings; never report unmeasured usage as zero.
        embeddings = getattr(client, "embedding_usage", None)
        if not isinstance(embeddings, UsageMeter):
            embeddings = None
        return cls(
            chat_input_tokens=chat.prompt_tokens,
            chat_output_tokens=chat.completion_tokens,
            chat_requests=chat.requests,
            chat_cache_hits=chat.cache_hits,
            embedding_input_tokens=embeddings.prompt_tokens if embeddings else None,
            embedding_requests=embeddings.requests if embeddings else None,
            embedding_cache_hits=embeddings.cache_hits if embeddings else None,
        )


class UsageCollector:
    """Accumulates usage attributable to one stage attempt, including failed attempts.

    Meters are cumulative per client, so the collector records the delta between
    ``open`` and ``add``; a client reused across stages is therefore never double-counted.
    """

    __slots__ = ("_baseline", "total")

    def __init__(self) -> None:
        self.total = UsageTotals()
        self._baseline: dict[int, UsageTotals] = {}

    def open(self, client: ChatClient | None) -> None:
        if client is not None:
            self._baseline[id(client)] = UsageTotals.from_client(client)

    def add(self, client: ChatClient | None) -> None:
        if client is None:
            return
        baseline = self._baseline.pop(id(client), UsageTotals())
        self.total = self.total + (UsageTotals.from_client(client) - baseline)


class StageRecord(StrictModel):
    status: StageStatus = "pending"
    attempts: int = Field(0, ge=0)
    output: str | None = None
    recovery_source: str | None = None
    last_error: str | None = None
    completed_at: datetime | None = None
    usage: UsageTotals = Field(default_factory=UsageTotals)


class StudyJournal(StrictModel):
    schema_version: Literal["study-v1"] = "study-v1"
    identity: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stages: dict[StageName, StageRecord] = Field(
        default_factory=lambda: {name: StageRecord() for name in STAGES}
    )


class StudyOutcome(StrictModel):
    completed: bool
    stages: dict[StageName, StageRecord]
    report_dir: Path | None
    usage: UsageTotals


def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def load_journal(study_dir: Path) -> StudyJournal | None:
    path = study_dir / _JOURNAL
    if not path.is_file():
        return None
    return StudyJournal.model_validate_json(path.read_text(encoding="utf-8"))


def _save_journal(study_dir: Path, journal: StudyJournal) -> StudyJournal:
    journal = journal.model_copy(update={"updated_at": datetime.now(UTC)})
    _write_atomic(study_dir / _JOURNAL, journal.model_dump_json(indent=2))
    return journal


# ------------------------------------------------------------- classification


class StageFailureError(SocietyError):
    """A stage attempt failed; ``recoverable`` decides whether the orchestrator retries."""

    def __init__(self, stage: StageName, cause: BaseException, *, recoverable: bool) -> None:
        super().__init__(f"{stage} failed: {cause}")
        self.stage = stage
        self.recoverable = recoverable


def classify(exc: BaseException) -> bool:
    """True when another attempt can make progress without changing inputs."""
    if isinstance(exc, SpecError | ValueError):
        return False
    if isinstance(exc, LLMError):
        return exc.category not in PERMANENT_LLM_CATEGORIES
    return isinstance(exc, OSError | sqlite3.Error | SocietyError)


# ------------------------------------------------------------------- stages


class StudyContext(StrictModel):
    audience: AudienceSpec
    scenario: ScenarioSpec
    graph_config: GraphConfig
    seed: int = Field(ge=0)
    enrich: bool
    llm_report: bool
    narrative: bool
    settings_hash: str


class Inputs(StrictModel):
    """Durable artifact locations produced by completed stages."""

    personas: Path | None = None
    graph: Path | None = None
    simulation: Path | None = None


class Stage(Protocol):
    name: StageName

    async def run(
        self,
        ctx: StudyContext,
        attempt_dir: Path,
        retry_from: Path | None,
        inputs: Inputs,
        usage: UsageCollector,
    ) -> None: ...


ClientFactory = Callable[[Settings], ChatClient]


class _PopulationStage:
    name: StageName = "population"

    def __init__(self, settings: Settings, factory: ClientFactory) -> None:
        self._settings = settings
        self._factory = factory

    async def run(
        self,
        ctx: StudyContext,
        attempt_dir: Path,
        retry_from: Path | None,
        inputs: Inputs,
        usage: UsageCollector,
    ) -> None:
        out = attempt_dir / "personas.jsonl"
        client = self._factory(self._settings) if ctx.enrich else None
        usage.open(client)
        try:
            builder = PopulationBuilder(
                client,
                chat_model=self._settings.chat_model,
                embed_model=self._settings.embed_model,
            )
            result = await builder.build(
                ctx.audience,
                seed=ctx.seed,
                recovery_dir=attempt_dir / "recovery",
                retry_from=retry_from / "recovery" if retry_from else None,
                settings_hash=ctx.settings_hash,
            )
        finally:
            usage.add(client)
            if client is not None:
                await client.aclose()
        write_jsonl(out, result.personas)
        _write_atomic(
            attempt_dir / "personas.manifest.json", result.manifest.model_dump_json(indent=2)
        )


class _GraphStage:
    name: StageName = "graph"

    async def run(
        self,
        ctx: StudyContext,
        attempt_dir: Path,
        retry_from: Path | None,
        inputs: Inputs,
        usage: UsageCollector,
    ) -> None:
        if inputs.personas is None:
            raise ValueError("graph stage requires a completed population")
        people = list(read_jsonl(inputs.personas, Persona))
        result = GraphBuilder(ctx.graph_config, seed=ctx.seed).build(people)
        result.graph.save(attempt_dir)
        _write_atomic(
            attempt_dir / "graph.manifest.json", result.manifest.model_dump_json(indent=2)
        )


class _SimulationStage:
    name: StageName = "simulation"

    def __init__(self, settings: Settings, factory: ClientFactory) -> None:
        self._settings = settings
        self._factory = factory

    async def run(
        self,
        ctx: StudyContext,
        attempt_dir: Path,
        retry_from: Path | None,
        inputs: Inputs,
        usage: UsageCollector,
    ) -> None:
        if inputs.personas is None or inputs.graph is None:
            raise ValueError("simulation stage requires a completed population and graph")
        people = list(read_jsonl(inputs.personas, Persona))
        graph = SocialGraph.load(inputs.graph)
        client = self._factory(self._settings)
        usage.open(client)
        try:
            await SimulationEngine(
                client,
                personas=people,
                graph=graph,
                scenario=ctx.scenario,
                seed=ctx.seed,
                out_dir=attempt_dir,
                chat_model=self._settings.chat_model,
                retry_from=retry_from,
                settings_hash=ctx.settings_hash,
            ).run()
        finally:
            usage.add(client)
            await client.aclose()


class _ReportStage:
    name: StageName = "report"

    def __init__(self, settings: Settings, factory: ClientFactory) -> None:
        self._settings = settings
        self._factory = factory

    async def run(
        self,
        ctx: StudyContext,
        attempt_dir: Path,
        retry_from: Path | None,
        inputs: Inputs,
        usage: UsageCollector,
    ) -> None:
        if inputs.personas is None or inputs.graph is None or inputs.simulation is None:
            raise ValueError("report stage requires population, graph and simulation outputs")
        people = list(read_jsonl(inputs.personas, Persona))
        graph = SocialGraph.load(inputs.graph)
        client = self._factory(self._settings) if ctx.llm_report else None
        usage.open(client)
        try:
            report = await ReportBuilder(client, seed=ctx.seed, narrative=ctx.narrative).build(
                personas=people, graph=graph, sim_dir=inputs.simulation, scenario=ctx.scenario
            )
        finally:
            usage.add(client)
            if client is not None:
                await client.aclose()
        ReportBuilder.write(report, attempt_dir)


# --------------------------------------------------------------- orchestrator


class StudyRunner:
    """Runs stages in order with bounded, recovery-aware retries and a durable journal."""

    __slots__ = ("_ctx", "_dir", "_journal", "_max_retries", "_stages")

    def __init__(
        self,
        study_dir: Path,
        ctx: StudyContext,
        *,
        stages: Sequence[Stage],
        max_retries: int,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if [stage.name for stage in stages] != list(STAGES):
            raise ValueError("stages must be population, graph, simulation, report in order")
        self._dir = study_dir
        self._ctx = ctx
        self._stages = tuple(stages)
        self._max_retries = max_retries
        self._journal = self._open()

    # ---------------------------------------------------------------- journal
    def _open(self) -> StudyJournal:
        identity = ResponseCache.key(
            study="study-v1",
            context=self._ctx.model_dump(mode="json"),
        )
        existing = load_journal(self._dir)
        if existing is None:
            if self._dir.exists() and any(self._dir.iterdir()):
                raise ValueError(
                    "Study directory exists but has no journal; use an empty directory"
                )
            self._dir.mkdir(parents=True, exist_ok=True)
            return _save_journal(self._dir, StudyJournal(identity=identity))
        if existing.identity != identity:
            raise ValueError("Study inputs, settings or options differ from the existing journal")
        return existing

    def _update(self, name: StageName, **changes: object) -> None:
        record = self._journal.stages[name].model_copy(update=changes)
        stages = {**self._journal.stages, name: record}
        self._journal = _save_journal(
            self._dir, self._journal.model_copy(update={"stages": stages})
        )

    # ------------------------------------------------------------------- run
    async def run(self) -> StudyOutcome:
        inputs = Inputs()
        try:
            for stage in self._stages:
                record = self._journal.stages[stage.name]
                if record.status != "completed":
                    await self._run_stage(stage, inputs)
                    record = self._journal.stages[stage.name]
                output = Path(record.output or "")
                inputs = self._with_output(inputs, stage.name, output)
            (self._dir / _SUCCESS).touch(exist_ok=True)
        finally:
            self._log_usage()
        report = self._journal.stages["report"].output
        return StudyOutcome(
            completed=True,
            stages=dict(self._journal.stages),
            report_dir=Path(report) if report else None,
            usage=self.total_usage(),
        )

    def total_usage(self) -> UsageTotals:
        total = UsageTotals()
        for record in self._journal.stages.values():
            total = total + record.usage
        return total

    def _log_usage(self) -> None:
        """Cumulative across every attempt of every stage, including failed ones and reruns."""
        total = self.total_usage()
        embedding_metered = total.embedding_input_tokens is not None
        _log.info(
            "token_usage_summary",
            extra={
                "stage": "study",
                "output": str(self._dir),
                "accounting_scope": "all_attempts_all_stages_this_study",
                "chat_input_tokens": total.chat_input_tokens,
                "chat_output_tokens": total.chat_output_tokens,
                "chat_requests": total.chat_requests,
                "chat_cache_hits": total.chat_cache_hits,
                "embedding_input_tokens": total.embedding_input_tokens,
                "embedding_cache_hits": total.embedding_cache_hits,
                "total_input_tokens": (
                    total.chat_input_tokens + (total.embedding_input_tokens or 0)
                ),
                "total_output_tokens": total.chat_output_tokens,
                "embedding_meter_available": embedding_metered,
                "per_stage": {
                    name: {
                        "attempts": rec.attempts,
                        "status": rec.status,
                        "chat_input_tokens": rec.usage.chat_input_tokens,
                        "chat_output_tokens": rec.usage.chat_output_tokens,
                        "chat_requests": rec.usage.chat_requests,
                        "chat_cache_hits": rec.usage.chat_cache_hits,
                        "embedding_input_tokens": rec.usage.embedding_input_tokens,
                    }
                    for name, rec in self._journal.stages.items()
                },
            },
        )

    async def _run_stage(self, stage: Stage, inputs: Inputs) -> None:
        """Retry budget is per invocation: an operator relaunching is an explicit decision."""
        name = stage.name
        tries_this_run = 0
        while True:
            record = self._journal.stages[name]
            attempt = record.attempts + 1
            tries_this_run += 1
            attempt_dir = self._dir / name / f"attempt-{attempt:02d}"
            # Recover from the previous attempt whether it failed or was interrupted mid-run.
            retry_from = (
                Path(record.output)
                if record.output and record.status in {"failed", "exhausted", "running"}
                else None
            )
            self._update(
                name,
                status="running",
                attempts=attempt,
                output=str(attempt_dir),
                recovery_source=str(retry_from) if retry_from else None,
            )
            _log.info(
                "stage_start", extra={"stage": name, "attempt": attempt, "retry_from": retry_from}
            )
            usage = UsageCollector()
            try:
                await stage.run(self._ctx, attempt_dir, retry_from, inputs, usage)
            except Exception as exc:
                recoverable = classify(exc)
                self._update(
                    name,
                    status="failed",
                    last_error=f"{type(exc).__name__}: {exc}",
                    usage=record.usage + usage.total,
                )
                _log.warning(
                    "stage_failed",
                    extra={
                        "stage": name,
                        "attempt": attempt,
                        "recoverable": recoverable,
                        "attempt_chat_input_tokens": usage.total.chat_input_tokens,
                        "attempt_chat_output_tokens": usage.total.chat_output_tokens,
                    },
                )
                if not recoverable or tries_this_run > self._max_retries:
                    self._update(name, status="exhausted")
                    raise StageFailureError(name, exc, recoverable=recoverable) from exc
                continue
            self._update(
                name,
                status="completed",
                completed_at=datetime.now(UTC),
                last_error=None,
                usage=record.usage + usage.total,
            )
            _log.info(
                "stage_done",
                extra={
                    "stage": name,
                    "attempt": attempt,
                    "attempt_chat_input_tokens": usage.total.chat_input_tokens,
                    "attempt_chat_output_tokens": usage.total.chat_output_tokens,
                },
            )
            return

    @staticmethod
    def _with_output(inputs: Inputs, name: StageName, output: Path) -> Inputs:
        if name == "population":
            return inputs.model_copy(update={"personas": output / "personas.jsonl"})
        if name == "graph":
            return inputs.model_copy(update={"graph": output})
        if name == "simulation":
            return inputs.model_copy(update={"simulation": output})
        return inputs


# -------------------------------------------------------------------- facade


def default_stages(settings: Settings, factory: ClientFactory = create_client) -> list[Stage]:
    return [
        _PopulationStage(settings, factory),
        _GraphStage(),
        _SimulationStage(settings, factory),
        _ReportStage(settings, factory),
    ]


def build_context(
    *,
    audience: Path,
    scenario: Path,
    seed: int,
    enrich: bool,
    llm_report: bool,
    narrative: bool,
    graph_config: GraphConfig,
    settings: Settings,
) -> StudyContext:
    return StudyContext(
        audience=AudienceSpec.from_yaml(audience),
        scenario=ScenarioSpec.from_yaml(scenario),
        graph_config=graph_config,
        seed=seed,
        enrich=enrich,
        llm_report=llm_report,
        narrative=narrative,
        settings_hash=ResponseCache.key(
            settings=settings.model_dump(mode="json", exclude={"openrouter_api_key"})
        ),
    )


def describe(study_dir: Path) -> str:
    journal = load_journal(study_dir)
    if journal is None:
        return json.dumps({"study": str(study_dir), "status": "missing"})
    total = UsageTotals()
    for record in journal.stages.values():
        total = total + record.usage
    return json.dumps(
        {
            "study": str(study_dir),
            "success": (study_dir / _SUCCESS).is_file(),
            "updated_at": journal.updated_at.isoformat(),
            "usage": total.model_dump(mode="json"),
            "stages": {
                name: {
                    "status": record.status,
                    "attempts": record.attempts,
                    "output": record.output,
                    "last_error": record.last_error,
                    "usage": record.usage.model_dump(mode="json"),
                }
                for name, record in journal.stages.items()
            },
        },
        indent=2,
    )
