"""`society population build --audience examples/audience.yaml --seed 42 --out personas.jsonl`"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer

from society import logging as slog
from society.config import Settings
from society.errors import SocietyError
from society.llm import OllamaClient, ResponseCache
from society.population import PopulationBuilder
from society.schemas import AudienceSpec, Persona
from society.storage import write_jsonl, read_jsonl
from society.graph import GraphBuilder, GraphConfig, SocialGraph
from society.sim import ScenarioSpec, SimulationEngine
from society.report import ReportBuilder


app = typer.Typer(no_args_is_help=True, add_completion=False, help="Synthetic Society CLI")

population_app = typer.Typer(no_args_is_help=True, help="Build and inspect populations")
graph_app = typer.Typer(no_args_is_help=True, help="Build the social graph")
sim_app = typer.Typer(no_args_is_help=True, help="Run a scenario against a population")
report_app = typer.Typer(no_args_is_help=True, help="Turn a simulation into a report")

app.add_typer(population_app, name="population")
app.add_typer(graph_app, name="graph")
app.add_typer(sim_app, name="sim")
app.add_typer(report_app, name="report")

_log = logging.getLogger("society.cli")


async def _build(spec: AudienceSpec, seed: int, enrich: bool, settings: Settings) -> tuple[int, Path]:
    client = OllamaClient(settings, ResponseCache(settings.cache_path)) if enrich else None
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
            client = OllamaClient(settings, ResponseCache(settings.cache_path)) if enrich else None
            try:
                builder = PopulationBuilder(
                    client, chat_model=settings.chat_model, embed_model=settings.embed_model
                )
                result = await builder.build(spec, seed=seed)
            finally:
                if client:
                    await client.aclose()
                    
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
            client = OllamaClient(settings, ResponseCache(settings.cache_path))
            try:
                engine = SimulationEngine(
                    client, personas=people, graph=g, scenario=spec, seed=seed,
                    out_dir=out_dir, chat_model=settings.chat_model,
                )
                result = await engine.run()
            finally:
                await client.aclose()
            m = result.manifest
            _log.info("done", extra={
                "events": str(result.events_path),
                "rounds": m.rounds,
                "llm_calls": sum(r.llm_calls for r in m.per_round),
                "final_adoption": m.per_round[-1].adoption if m.per_round else None,
                "prompt_tokens": m.prompt_tokens, "completion_tokens": m.completion_tokens,
            })
 
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
    llm: Annotated[bool, typer.Option(help="Use Ollama for objection clustering + narrative")] = True,
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
            client = OllamaClient(settings, ResponseCache(settings.cache_path)) if llm else None
            try:
                report = await ReportBuilder(client, seed=seed, narrative=narrative).build(
                    personas=people, graph=g, sim_dir=sim, scenario=spec)
            finally:
                if client:
                    await client.aclose()
            js, md = ReportBuilder.write(report, out_dir)
            _log.info("done", extra={"json": str(js), "markdown": str(md), "verdict": report.headline.verdict,
                                     "final_adoption": report.headline.final_adoption})
 
        asyncio.run(run())
    except (SocietyError, ValueError, OSError) as exc:
        _log.error("failed", extra={"error": str(exc)})
        raise typer.Exit(code=1) from exc



if __name__ == "__main__":
    app()
