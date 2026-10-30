"""Layer 1 orchestrator: sample → enrich → dedupe/regenerate → manifest."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from pydantic import Field

from society.llm.base import ChatClient
from society.llm.cache import ResponseCache
from society.population import enricher as enrichment_prompts
from society.population.diversity import DiversityFilter
from society.population.enricher import PersonaEnricher
from society.population.sampler import PopulationSampler
from society.recovery import RecoveryJournal
from society.schemas import AudienceSpec, Persona, PersonaProfile, RunManifest, StrictModel

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BuildResult:
    personas: list[Persona]
    manifest: RunManifest


class PopulationProgress(StrictModel):
    nonce: int = Field(ge=0)
    targets: list[int]
    regenerated: int = Field(ge=0)
    complete: bool = False


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

    async def build(
        self,
        spec: AudienceSpec,
        *,
        seed: int,
        recovery_dir: Path | None = None,
        retry_from: Path | None = None,
        settings_hash: str = "",
    ) -> BuildResult:
        personas = PopulationSampler(spec, seed).sample()
        _log.info("sampled", extra={"size": len(personas), "seed": seed})
        digest = hashlib.sha256()
        for persona in personas:
            digest.update(persona.model_dump_json().encode())
            digest.update(b"\n")
        identity = ResponseCache.key(
            stage="population-recovery-v1",
            spec=spec.model_dump(mode="json"),
            seed=seed,
            settings_hash=settings_hash,
            chat_model=self._chat_model,
            embed_model=self._embed_model,
            enrich=self._client is not None,
            max_passes=self._max_passes,
            prompts=(enrichment_prompts._SYSTEM, enrichment_prompts._USER_TMPL),
            response_schema=PersonaProfile.model_json_schema(),
            sampled=digest.hexdigest(),
        )
        with RecoveryJournal(recovery_dir, identity=identity, source=retry_from) as journal:
            personas, regenerated = await self._enrich(personas, spec, seed, journal)

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

    async def _enrich(
        self, personas: list[Persona], spec: AudienceSpec, seed: int, journal: RecoveryJournal
    ) -> tuple[list[Persona], int]:
        progress = journal.state(PopulationProgress)
        if progress is None:
            progress = PopulationProgress(
                nonce=0, targets=list(range(len(personas))), regenerated=0
            )
            journal.advance(progress)
        for nonce in range(progress.nonce):
            for index, profile in journal.values(f"profiles:{nonce}", PersonaProfile):
                if not 0 <= index < len(personas):
                    raise ValueError("Saved profile index is outside the population")
                personas[index] = personas[index].with_profile(profile)

        if self._client is not None:
            enricher = PersonaEnricher(self._client, spec, seed=seed)
            dedupe = DiversityFilter(self._client, spec.diversity)
            while not progress.complete:
                nonce = progress.nonce
                scope = f"profiles:{nonce}"
                saved = dict(journal.values(scope, PersonaProfile))
                personas = await enricher.enrich(
                    personas,
                    only=progress.targets,
                    nonce=nonce,
                    saved=saved,
                    on_profile=partial(journal.save, scope),
                )
                if nonce >= self._max_passes:
                    progress = progress.model_copy(update={"complete": True})
                    journal.advance(progress)
                    break
                dupes = await dedupe.duplicates(personas)
                if not dupes:
                    progress = progress.model_copy(update={"complete": True})
                    journal.advance(progress)
                    break
                _log.info(
                    "regenerating_duplicates",
                    extra={"count": len(dupes), "pass": nonce + 1},
                )
                progress = PopulationProgress(
                    nonce=nonce + 1,
                    targets=dupes,
                    regenerated=progress.regenerated + len(dupes),
                )
                journal.advance(progress)
            if progress.complete:
                for index, profile in journal.values(f"profiles:{progress.nonce}", PersonaProfile):
                    if not 0 <= index < len(personas):
                        raise ValueError("Saved profile index is outside the population")
                    personas[index] = personas[index].with_profile(profile)
        else:
            journal.advance(progress.model_copy(update={"complete": True}))
        return personas, progress.regenerated
