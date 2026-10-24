"""`society population build --audience examples/audience.yaml --seed 42 --out personas.jsonl`"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from pathlib import Path
from typing import Annotated, Literal

import typer

from society import logging as slog
from society.config import Settings
from society.errors import SocietyError
from society.llm.factory import create_client
from society.llm.base import ChatClient, UsageMeter
from society.llm.openrouter import OpenRouterClient
from society.population import PopulationBuilder
from society.schemas import AudienceSpec, Persona
from society.storage import write_jsonl, read_jsonl
from society.graph import GraphBuilder, GraphConfig, SocialGraph
from society.sim import ScenarioSpec, SimulationEngine
from society.report import ReportBuilder
from society.population.sampler import PopulationSampler
from society.report.metrics import summarize_trial
from society.report.render import trial_to_markdown
from society.sim.engine import run_trial
from society.sim.prompts import TRIAL_PROMPT_VERSION
from society.sim.schemas import TrialRecord, TrialScenarioSpec


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
    stage: Literal["population", "simulation", "report"],
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
        "embedding_input_tokens": (
            embeddings.prompt_tokens if embeddings is not None else None
        ),
        "embedding_output_tokens": (
            embeddings.completion_tokens if embeddings is not None else None
        ),
        "total_input_tokens": (
            chat.prompt_tokens + embeddings.prompt_tokens
            if embeddings is not None
            else None
        ),
        "total_output_tokens": (
            chat.completion_tokens + embeddings.completion_tokens
            if embeddings is not None
            else None
        ),
        "chat_cache_hits": chat.cache_hits,
        "embedding_cache_hits": (
            embeddings.cache_hits if embeddings is not None else None
        ),
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
) -> None:
    slog.configure(log_level)
    settings = Settings()

    try:
        spec = AudienceSpec.from_yaml(audience)

        async def run() -> None:
            client = create_client(settings) if enrich else None
            try:
                builder = PopulationBuilder(
                    client, chat_model=settings.chat_model, embed_model=settings.embed_model
                )
                result = await builder.build(spec, seed=seed)
            finally:
                await _close_with_usage(
                    client,
                    stage="population",
                    settings=settings,
                    output=out
                )

            n = write_jsonl(out, result.personas)
            manifest_path = out.with_suffix(".manifest.json")
            manifest_path.write_text(result.manifest.model_dump_json(indent=2))

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

    except SocietyError as exc:
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
) -> None:
    slog.configure(log_level)
    settings = Settings()
    try:
        people = list(read_jsonl(personas, Persona))
        g = SocialGraph.load(graph)
        spec = ScenarioSpec.from_yaml(scenario)

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
                )
                result = await engine.run()
            finally:
                await _close_with_usage(
                    client,
                    stage="simulation",
                    settings=settings,
                    output=out_dir
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
    except (SocietyError, ValueError, OSError) as exc:
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
                        client,
                        stage="report",
                        settings=settings,
                        output=out_dir
                    )
            js, md = ReportBuilder.write(report, out_dir)
            _log.info(
                "done",
                extra={
                    "json": str(js),
                    "markdown": str(md),
                    "html": str(out_dir / "report.html"),
                    "verdict": report.headline.verdict,
                    "final_adoption": report.headline.final_adoption,
                },
            )

        asyncio.run(run())
    except (SocietyError, ValueError, OSError) as exc:
        _log.error("failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


@survey_app.command("run")
def survey_run(
    audience: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    scenario: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    out_dir: Annotated[Path, typer.Option()] = Path("out/survey"),
    seed: Annotated[int, typer.Option(min=0)] = 42,
    log_level: Annotated[str, typer.Option()] = "INFO",
) -> None:
    slog.configure(log_level)
    try:
        audience_spec = AudienceSpec.from_yaml(audience)
        scenario_spec = TrialScenarioSpec.from_yaml(scenario)
        settings = Settings()

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
                {
                    "seed": seed,
                    "prompt_version": TRIAL_PROMPT_VERSION,
                    "persona_mode": "attributes_only",
                    "aggregation": "unweighted",
                    "temperature": 0.7,
                    "settings": settings.model_dump(
                        mode="json", exclude={"openrouter_api_key"}
                    ),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # No LLM biographies, deduplication embeddings, or social graph.
        # Traits are generated by the existing sampler but never sent to the model.
        people = PopulationSampler(audience_spec, seed).sample()
        write_jsonl(out_dir / "personas.json1", people)

        async def run() -> list[TrialRecord]:
            client = create_client(settings)
            try:
                return await run_trial(
                    client,
                    personas=people,
                    audience=audience_spec.audience,
                    scenario=scenario_spec,
                    seed=seed,
                    concurrency=settings.concurrency,
                )
            finally:
                await _close_with_usage(
                    client,
                    stage="survey",
                    settings=settings,
                    output=out_dir,
                )

        records = asyncio.run(run())
        write_jsonl(out_dir / "responses.jsonl", records)
        report = summarize_trial(
            records, scenario_spec, expected_n=audience_spec.size
        )
        # Diagnostic summary is allowed for failed runs; it is not a deliverable.
        (out_dir / "run.summary.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        if report.technical_failures:
            raise SocietyError(
                f"{report.technical_failures} survey requests failed; "
                "diagnostics saved, final report withheld. Restart in a fresh directory."
            )

        markdown = trial_to_markdown(report)
        (out_dir / "report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        (out_dir / "report.md").write_text(markdown, encoding="utf-8")
        # Intentionally minimal, offline HTML; no generated text becomes HTML markup.
        (out_dir / "report.html").write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; base-uri \'none\'; form-action \'none\'">'
            "<title>Cohuvo survey report</title></head><body><pre>"
            + html.escape(markdown)
            + "</pre></body></html>",
            encoding="utf-8",
        )
        (out_dir / "SUCCESS").touch(exist_ok=False)
        _log.info("survey_done", extra={"out": str(out_dir), "valid": report.valid})
    except (SocietyError, ValueError, OSError) as exc:
        _log.error("survey_failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
