"""Layer 1 orchestrator: sample → enrich → dedupe/regenerate → manifest."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from society.llm.base import ChatClient
from society.population.diversity import DiversityFilter
from society.population.enricher import PersonaEnricher
from society.population.sampler import PopulationSampler
from society.schemas import AudienceSpec, Persona, RunManifest

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BuildResult:
    personas: list[Persona]
    manifest: RunManifest


class PopulationBuilder:
    __slots__ = ("_chat_model", "_client", "_embed_model", "_max_passes")

    def __init__(
        self,
        client: ChatClient | None,
        *,
        chat_model: str | None = None,
        embed_model: str | None = None,
        max_dedupe_passes: int = 2,
    ) -> None:
        self._client = client
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._max_passes = max_dedupe_passes

    async def build(self, spec: AudienceSpec, *, seed: int) -> BuildResult:
        personas = PopulationSampler(spec, seed).sample()
        regenerated = 0
        _log.info("sampled", extra={"size": len(personas), "seed": seed})

        if self._client is not None:
            enricher = PersonaEnricher(self._client, spec, seed=seed)
            dedupe = DiversityFilter(self._client, spec.diversity)
            personas = await enricher.enrich(personas)
            for nonce in range(1, self._max_passes + 1):
                dupes = await dedupe.duplicates(personas)
                if not dupes:
                    break

                _log.info(
                    "regenerating_duplicates",
                    extra={"count": len(dupes), "pass": nonce},
                )
                regenerated += len(dupes)
                personas = await enricher.enrich(personas, only=dupes, nonce=nonce)

        usage = self._client.usage if self._client else None
        manifest = RunManifest(
            run_id=uuid.uuid4().hex[:12],
            spec_hash=spec.content_hash(),
            seed=seed,
            size=len(personas),
            chat_model=self._chat_model if self._client else None,
            embed_model=self._embed_model if self._client else None,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            regenerated=regenerated,
        )
        return BuildResult(personas=personas, manifest=manifest)
