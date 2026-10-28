"""Layer 1B — give each persona a narrative via batched, bounded, cached LLM calls.

Per-persona `seed` is derived from (global seed, index, nonce) so a rerun is
deterministic and a regeneration pass (nonce+1) yields a genuinely new bio.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from society.errors import LLMError
from society.llm.base import ChatClient, JsonRequest
from society.schemas import AudienceSpec, Persona, PersonaProfile

_log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a demographer writing realistic, specific, non-stereotypical persona cards for "
    "market research. Write in third person, present tense. Avoid clichés and generic phrasing. "
    "Never mention that the person is fictional. Return JSON only."
)

_USER_TMPL = """Audience: {audience}

Structured facts about this specific person (treat as ground truth):
{facts}

Psychographics (1 = low, 5 = high):
- openness to new products: {openness}
- price sensitivity: {price_sensitivity}
- skepticism of marketing: {skepticism}
- social influence (0-1): {influence}
- decision style: {decision_style}
- buyer segment: {segment}  (non_buyer = currently has no intention to spend on this problem)

Produce:
- name: a plausible full name consistent with a US suburban context
- city: "City, ST"
- bio: 80-140 words of concrete daily-life context relevant to the audience
- current_solution: how they handle the pain points today
- switch_trigger: the one thing that would make them change behaviour
Variation hint #{nonce}: make this person distinct from typical examples."""

_SEED_MIX = 0x9E3779B1  # golden-ratio constant; decorrelates per-persona seeds


def _persona_seed(global_seed: int, index: int, nonce: int) -> int:
    return (global_seed * _SEED_MIX + index * 7919 + nonce * 104_729) & 0x7FFF_FFFF


class PersonaEnricher:
    __slots__ = ("_client", "_seed", "_spec", "_temperature")

    def __init__(
        self, client: ChatClient, spec: AudienceSpec, *, seed: int, temperature: float = 0.9
    ) -> None:
        self._client = client
        self._spec = spec
        self._seed = seed
        self._temperature = temperature

    async def enrich(
        self, personas: Sequence[Persona], *, only: Sequence[int] | None = None, nonce: int = 0
    ) -> list[Persona]:
        targets = sorted(set(only)) if only is not None else list(range(len(personas)))
        out = list(personas)

        failed = 0
        async for position, profile in self._client.complete_json_many(
            (self._request(personas[i], nonce) for i in targets),
            schema=PersonaProfile,
            temperature=self._temperature,
        ):
            i = targets[position]
            if isinstance(profile, LLMError):
                failed += 1
                _log.warning("enrichment_failed", extra={"persona_index": i, "nonce": nonce})
                continue
            out[i] = out[i].with_profile(profile)
        if failed:
            raise LLMError(f"{failed} persona enrichments failed; rerun to retry.")
        _log.info("enriched", extra={"count": len(targets), "nonce": nonce})
        return out

    def _request(self, persona: Persona, nonce: int) -> JsonRequest:
        t = persona.traits
        user = _USER_TMPL.format(
            audience=self._spec.audience,
            facts=json.dumps(persona.attributes, indent=0, ensure_ascii=False),
            openness=t.openness,
            price_sensitivity=t.price_sensitivity,
            skepticism=t.skepticism,
            influence=t.influence,
            decision_style=t.decision_style.value,
            segment=t.segment.value,
            nonce=nonce,
        )
        return JsonRequest(
            system=_SYSTEM,
            user=user,
            seed=_persona_seed(self._seed, persona.index, nonce),
        )
