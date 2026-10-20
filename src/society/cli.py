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
from society.schemas import AudienceSpec
from society.storage import write_jsonl


app = typer.Typer(no_args_is_help=True, add_completion=False, help="Synthetic Society CLI")
population_app = typer.Typer(no_args_is_help=True, help="Build and inspect populations.")
app.add_typer(population_app, name="population")
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


if __name__ == "__main__":
    app()
