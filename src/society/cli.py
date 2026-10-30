"""`society population build --audience examples/audience.yaml --seed 42 --out personas.jsonl`"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Literal

import typer

from society import logging as slog
from society.config import Settings
from society.errors import SocietyError
from society.graph import GraphBuilder, GraphConfig, SocialGraph
from society.llm.base import ChatClient, UsageMeter
from society.llm.cache import ResponseCache
from society.llm.factory import create_client
from society.llm.openrouter import OpenRouterClient
from society.population import PopulationBuilder
from society.population.sampler import PopulationSampler
from society.report import ReportBuilder
from society.report.metrics import summarize_trial
from society.report.render import trial_to_markdown
from society.schemas import AudienceSpec, Persona
from society.sim import ScenarioSpec, SimulationEngine
from society.sim.engine import run_trial
from society.sim.prompts import TRIAL_PROMPT_VERSION
from society.sim.schemas import TrialRecord, TrialScenarioSpec
from society.storage import read_jsonl, write_jsonl, write_jsonl_async

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Cohuvo audience simulation CLI")

population_app = typer.Typer(no_args_is_help=True, help="Build and inspect populations")
graph_app = typer.Typer(no_args_is_help=True, help="Build the social graph")
sim_app = typer.Typer(no_args_is_help=True, help="Run a scenario against a population")
report_app = typer.Typer(no_args_is_help=True, help="Turn a simulation into a report")
survey_app = typer.Typer(no_args_is_help=True, help="Run an independent trial survey")

app.add_typer(population_app, name="population")
app.add_typer(graph_app, name="graph")
app.add_typer(sim_app, name="sim")
app.add_typer(report_app, name="report")
app.add_typer(survey_app, name="survey")

_log = logging.getLogger("society.cli")


async def _close_with_usage(
    client: ChatClient | None,
    *,
    stage: Literal["population", "simulation", "report", "survey"],
    settings: Settings,
    output: Path,
) -> None:
    """Log observed usage for this invocation, including on operation failure."""
    chat = client.usage if client is not None else UsageMeter()

    # The current Ollama adapter does not meter embedding tokens.
    # Do not represent unmeasured usage as zero.
    embeddings: UsageMeter | None
    if client is None:
        embeddings = UsageMeter()
    elif isinstance(client, OpenRouterClient):
        embeddings = client.embedding_usage
    else:
        embeddings = None

    summary: dict[str, object] = {
        "stage": stage,
        "output": str(output),
        "provider": settings.provider,
        "chat_model": settings.chat_model,
        "embedding_model": settings.embed_model,
        "accounting_scope": "observed_response_usage_this_invocation",
        "chat_input_tokens": chat.prompt_tokens,
        "chat_output_tokens": chat.completion_tokens,
        "embedding_input_tokens": (embeddings.prompt_tokens if embeddings is not None else None),
        "embedding_output_tokens": (
            embeddings.completion_tokens if embeddings is not None else None
        ),
        "total_input_tokens": (
            chat.prompt_tokens + embeddings.prompt_tokens if embeddings is not None else None
        ),
        "total_output_tokens": (
            chat.completion_tokens + embeddings.completion_tokens
            if embeddings is not None
            else None
        ),
        "chat_cache_hits": chat.cache_hits,
        "embedding_cache_hits": (embeddings.cache_hits if embeddings is not None else None),
        "embedding_meter_available": embeddings is not None,
    }

    try:
        if client is not None:
            await client.aclose()
    finally:
        _log.info("token_usage_summary", extra=summary)


async def _build(
    spec: AudienceSpec, seed: int, enrich: bool, settings: Settings
) -> tuple[int, Path]:
    client = create_client(settings) if enrich else None
    try:
        builder = PopulationBuilder(
            client, chat_model=settings.chat_model, embed_model=settings.embed_model
        )
        result = await builder.build(spec, seed=seed)
    finally:
        if client:
            await client.aclose()

    return 0, Path()  # placeholder replaced below


@population_app.command("build")
def build(
    audience: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="audience.yaml")],
    out: Annotated[Path, typer.Option(help="Output personas JSONL")] = Path("personas.jsonl"),
    seed: Annotated[int, typer.Option(help="Deterministic seed")] = 42,
    enrich: Annotated[bool, typer.Option(help="Generate bios via LLM")] = True,
    log_level: Annotated[str, typer.Option()] = "INFO",
    retry_from: Annotated[
        Path | None,
        typer.Option(exists=True, file_okay=False, help="Population recovery directory."),
    ] = None,
) -> None:
    slog.configure(log_level)
    settings = Settings()

    try:
        spec = AudienceSpec.from_yaml(audience)
        manifest_path = out.with_suffix(".manifest.json")
        recovery_dir = out.with_suffix(".recovery")
        if out.exists() or manifest_path.exists() or recovery_dir.exists():
            raise ValueError("Population output, manifest and recovery directory must be fresh")
        settings_hash = ResponseCache.key(
            settings=settings.model_dump(mode="json", exclude={"openrouter_api_key"})
        )

        async def run() -> None:
            client = create_client(settings) if enrich else None
            try:
                builder = PopulationBuilder(
                    client, chat_model=settings.chat_model, embed_model=settings.embed_model
                )
                result = await builder.build(
                    spec,
                    seed=seed,
                    recovery_dir=recovery_dir,
                    retry_from=retry_from,
                    settings_hash=settings_hash,
                )
            finally:
                await _close_with_usage(client, stage="population", settings=settings, output=out)

            n = write_jsonl(out, result.personas)
            manifest_path.write_text(result.manifest.model_dump_json(indent=2))
            (recovery_dir / "SUCCESS").touch(exist_ok=False)

            _log.info(
                "done",
                extra={
                    "personas": n,
                    "out": str(out),
                    "manifest": str(manifest_path),
                    "prompt_tokens": result.manifest.prompt_tokens,
                    "completion_tokens": result.manifest.completion_tokens,
                    "regenerated": result.manifest.regenerated,
                },
            )

        asyncio.run(run())

    except (SocietyError, ValueError, OSError, sqlite3.Error) as exc:
        _log.error("failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


@graph_app.command("build")
def graph_build(
    personas: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="personas.jsonl")],
    out_dir: Annotated[Path, typer.Option(help="Output directory")] = Path("out/graph"),
    seed: Annotated[int, typer.Option()] = 42,
    mean_degree: Annotated[int, typer.Option(min=1, max=200)] = 8,
    rewire_prob: Annotated[float, typer.Option(min=0.0, max=1.0)] = 0.1,
    homophily_beta: Annotated[float, typer.Option(min=0.0)] = 4.0,
    influence_alpha: Annotated[float, typer.Option(min=0.0)] = 2.0,
    log_level: Annotated[str, typer.Option()] = "INFO",
) -> None:
    slog.configure(log_level)
    try:
        people = list(read_jsonl(personas, Persona))
        config = GraphConfig(
            mean_degree=mean_degree,
            rewire_prob=rewire_prob,
            homophily_beta=homophily_beta,
            influence_alpha=influence_alpha,
        )
        result = GraphBuilder(config, seed=seed).build(people)
        result.graph.save(out_dir)
        (out_dir / "graph.manifest.json").write_text(result.manifest.model_dump_json(indent=2))
        _log.info(
            "done",
            extra={
                "out": str(out_dir),
                "edges": result.manifest.edges,
                "mean_out_degree": round(result.manifest.mean_out_degree, 2),
                "max_in_degree": result.manifest.max_in_degree,
                "homophily_lift": result.manifest.homophily_lift,
                "channels": result.manifest.channels,
            },
        )
    except (SocietyError, ValueError, OSError) as exc:
        _log.error("failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


@sim_app.command("run")
def sim_run(
    personas: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    graph: Annotated[Path, typer.Option(exists=True, file_okay=False, help="graph directory")],
    scenario: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="scenario.yaml")],
    out_dir: Annotated[Path, typer.Option()] = Path("out/sim"),
    seed: Annotated[int, typer.Option()] = 42,
    log_level: Annotated[str, typer.Option()] = "INFO",
    retry_from: Annotated[
        Path | None,
        typer.Option(exists=True, file_okay=False, help="Failed simulation directory."),
    ] = None,
) -> None:
    slog.configure(log_level)
    settings = Settings()
    try:
        people = list(read_jsonl(personas, Persona))
        g = SocialGraph.load(graph)
        spec = ScenarioSpec.from_yaml(scenario)
        settings_hash = ResponseCache.key(
            settings=settings.model_dump(mode="json", exclude={"openrouter_api_key"})
        )

        async def run() -> None:
            client = create_client(settings)
            try:
                engine = SimulationEngine(
                    client,
                    personas=people,
                    graph=g,
                    scenario=spec,
                    seed=seed,
                    out_dir=out_dir,
                    chat_model=settings.chat_model,
                    retry_from=retry_from,
                    settings_hash=settings_hash,
                )
                result = await engine.run()
            finally:
                await _close_with_usage(
                    client, stage="simulation", settings=settings, output=out_dir
                )
            m = result.manifest
            _log.info(
                "done",
                extra={
                    "events": str(result.events_path),
                    "rounds": m.rounds,
                    "llm_calls": sum(r.llm_calls for r in m.per_round),
                    "final_adoption": m.per_round[-1].adoption if m.per_round else None,
                    "prompt_tokens": m.prompt_tokens,
                    "completion_tokens": m.completion_tokens,
                },
            )

        asyncio.run(run())
    except (SocietyError, ValueError, OSError, sqlite3.Error) as exc:
        _log.error("failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


@report_app.command("build")
def report_build(
    personas: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    graph: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    sim: Annotated[Path, typer.Option(exists=True, file_okay=False, help="sim output directory")],
    scenario: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    out_dir: Annotated[Path, typer.Option()] = Path("out/report"),
    seed: Annotated[int, typer.Option()] = 42,
    llm: Annotated[
        bool, typer.Option(help="Use embeddings and the configured chat provider for reporting")
    ] = True,
    narrative: Annotated[bool, typer.Option()] = True,
    log_level: Annotated[str, typer.Option()] = "INFO",
) -> None:
    slog.configure(log_level)
    settings = Settings()
    try:
        people = list(read_jsonl(personas, Persona))

        g = SocialGraph.load(graph)
        spec = ScenarioSpec.from_yaml(scenario)

        async def run() -> None:
            client = create_client(settings) if llm else None
            try:
                report = await ReportBuilder(client, seed=seed, narrative=narrative).build(
                    personas=people, graph=g, sim_dir=sim, scenario=spec
                )
            finally:
                if client:
                    await _close_with_usage(
                        client, stage="report", settings=settings, output=out_dir
                    )
            js = ReportBuilder.write(report, out_dir)
            _log.info(
                "done",
                extra={
                    "json": str(js),
                    "verdict": report.headline.verdict,
                    "final_adoption": report.headline.final_adoption,
                },
            )

        asyncio.run(run())
    except (SocietyError, ValueError, OSError) as exc:
        _log.error("failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


def _trial_recovery(
    source: Path,
    audience: AudienceSpec,
    scenario: TrialScenarioSpec,
    run_settings: dict[str, object],
    people: list[Persona],
) -> dict[int, TrialRecord]:
    if (
        AudienceSpec.model_validate_json(
            (source / "audience.effective.json").read_text(encoding="utf-8")
        )
        != audience
    ):
        raise ValueError("Retry audience does not match the original run")
    if (
        TrialScenarioSpec.model_validate_json(
            (source / "scenario.effective.json").read_text(encoding="utf-8")
        )
        != scenario
    ):
        raise ValueError("Retry scenario does not match the original run")
    previous_settings = json.loads((source / "run.settings.json").read_text(encoding="utf-8"))
    if previous_settings != run_settings:
        raise ValueError("Retry settings, seed or prompt version differ from the original run")
    if list(read_jsonl(source / "personas.jsonl", Persona)) != people:
        raise ValueError("Retry personas do not match the original run")
    records: dict[int, TrialRecord] = {}
    for record in read_jsonl(source / "responses.jsonl", TrialRecord):
        if (
            record.index in records
            or not 0 <= record.index < len(people)
            or record.persona_id != people[record.index].id
            or (record.answer is not None and record.answer.option_index >= len(scenario.options))
        ):
            raise ValueError("Retry source contains duplicate or invalid respondent records")
        records[record.index] = record
    if len(records) != len(people):
        raise ValueError("Retry source must contain one record per persona")
    if all(r.status == "answered" for r in records.values()):
        raise ValueError("Retry source has no technical failures")
    return records


@survey_app.command("run")
def survey_run(  # noqa: PLR0913, PLR0917
    audience: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    scenario: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    out_dir: Annotated[Path, typer.Option()] = Path("out/survey"),
    seed: Annotated[int, typer.Option(min=0)] = 42,
    log_level: Annotated[str, typer.Option()] = "INFO",
    retry_from: Annotated[
        Path | None,
        typer.Option(exists=True, file_okay=False, help="Reuse answers from a failed survey run."),
    ] = None,
) -> None:
    slog.configure(log_level)
    try:
        audience_spec = AudienceSpec.from_yaml(audience)
        scenario_spec = TrialScenarioSpec.from_yaml(scenario)
        settings = Settings()
        run_settings: dict[str, object] = {
            "seed": seed,
            "prompt_version": TRIAL_PROMPT_VERSION,
            "persona_mode": "attributes_only",
            "aggregation": "unweighted",
            "temperature": 0.7,
            "settings": settings.model_dump(mode="json", exclude={"openrouter_api_key"}),
        }
        people = PopulationSampler(audience_spec, seed).sample()
        previous = (
            _trial_recovery(retry_from, audience_spec, scenario_spec, run_settings, people)
            if retry_from is not None
            else {}
        )
        pending = {i for i, record in previous.items() if record.status == "technical_failure"}

        # Fresh directories only: no accidental resume or mixed-run artifacts.
        out_dir.mkdir(parents=True, exist_ok=False)
        (out_dir / "audience.effective.json").write_text(
            audience_spec.model_dump_json(indent=2), encoding="utf-8"
        )
        (out_dir / "scenario.effective.json").write_text(
            scenario_spec.model_dump_json(indent=2), encoding="utf-8"
        )
        (out_dir / "run.settings.json").write_text(
            json.dumps(
                run_settings,
                indent=2,
            ),
            encoding="utf-8",
        )

        # No LLM biographies, deduplication embeddings, or social graph.
        # Traits are generated by the existing sampler but never sent to the model.
        write_jsonl(out_dir / "personas.jsonl", people)
        responses_path = out_dir / "responses.jsonl"
        if retry_from is not None:
            (out_dir / "recovery.source.json").write_text(
                json.dumps({"source": str(retry_from.resolve()), "retry_count": len(pending)}),
                encoding="utf-8",
            )

        async def run() -> int:
            client = create_client(settings)

            async def records() -> AsyncIterator[TrialRecord]:
                retried = run_trial(
                    client,
                    personas=people,
                    audience=audience_spec.audience,
                    scenario=scenario_spec,
                    seed=seed,
                    only=pending if previous else None,
                )
                try:
                    for persona in people:
                        saved = previous.get(persona.index)
                        if saved is not None and saved.status == "answered":
                            yield saved
                        else:
                            record = await anext(retried)
                            if record.index != persona.index:
                                raise SocietyError("Survey response index mismatch")
                            yield record
                finally:
                    await retried.aclose()

            try:
                # Records stream to disk as batches complete; nothing is held per persona.
                return await write_jsonl_async(
                    responses_path,
                    records(),
                )
            finally:
                await _close_with_usage(
                    client,
                    stage="survey",
                    settings=settings,
                    output=out_dir,
                )

        asyncio.run(run())
        report = summarize_trial(
            read_jsonl(responses_path, TrialRecord), scenario_spec, expected_n=audience_spec.size
        )
        # Diagnostic summary is allowed for failed runs; it is not a deliverable.
        (out_dir / "run.summary.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        if report.technical_failures:
            raise SocietyError(
                f"{report.technical_failures} survey requests failed; "
                "diagnostics saved, final report withheld. Retry in a fresh output directory "
                f"with --retry-from {out_dir} and the same inputs and settings."
            )

        (out_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (out_dir / "SUCCESS").touch(exist_ok=False)
        _log.info("survey_done", extra={"out": str(out_dir), "valid": report.valid})
    except (SocietyError, ValueError, OSError) as exc:
        _log.error("survey_failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
