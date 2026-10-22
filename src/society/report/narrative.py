"""One LLM call. Input is a compact JSON of computed stats — the model summarises, never measures."""

from __future__ import annotations

import json

from society.llm.base import ChatClient
from society.report.schemas import (
    EventImpact,
    Headline,
    Narrative,
    ObjectionTheme,
    PriceCurve,
    SegmentStat,
)

_SYSTEM = (
    "You are a senior market researcher briefing a founder. Use ONLY the figures provided; never "
    "invent numbers, segments or quotes. Be direct and specific. Return JSON only."
)

_USER = """Scenario: {name}
 
Computed results (authoritative):
{stats}
 
Write `summary` (120-200 words: verdict, who it resonates with, the main blockers, pricing read, and
how it spread or stalled) and 3 concrete `recommendations` the founder can act on next week."""


def _compact(
    headline: Headline,
    segments: list[SegmentStat],
    price: PriceCurve,
    objections: list[ObjectionTheme],
    events: list[EventImpact],
) -> dict[str, object]:
    strong = [s for s in segments if not s.low_n]
    return {
        "headline": headline.model_dump(),
        "top_segments": [s.model_dump(exclude={"low_n"}) for s in strong[:5]],
        "weak_segments": [s.model_dump(exclude={"low_n"}) for s in strong[-3:]],
        "price": price.model_dump(exclude={"points"}),
        "objections": [o.model_dump(exclude={"quotes"}) for o in objections[:5]],
        "events": [e.model_dump() for e in events],
    }


async def write_narrative(
    client: ChatClient,
    *,
    name: str,
    headline: Headline,
    segments: list[SegmentStat],
    price: PriceCurve,
    objections: list[ObjectionTheme],
    events: list[EventImpact],
    seed: int,
) -> Narrative:
    stats = json.dumps(
        _compact(headline, segments, price, objections, events), separators=(",", ":")
    )
    return await client.complete_json(
        system=_SYSTEM,
        user=_USER.format(name=name, stats=stats),
        schema=Narrative,
        temperature=0.3,
        seed=seed,
    )
