"""One LLM call. Input is a compact JSON of computed stats — the model summarises, never measures."""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Sequence

from society.llm.base import ChatClient
from society.report.schemas import (
    Confidence,
    EventImpact,
    Headline,
    Narrative,
    ObjectionTheme,
    PriceCurve,
    RoundPoint,
    SegmentStat,
    SpreadStat,
)

_TOP_INFLUENCERS = 3

_SYSTEM = (
    "You are a senior market researcher briefing a founder. Use ONLY the figures provided; never "
    "invent numbers, segments or quotes. Be direct and specific. Return JSON only."
)

_USER = """Scenario: {name}
 
Computed results (authoritative):
{stats}
 
Write `summary` (120-200 words: verdict, who it resonates with and the weakest segment, the main
blockers, pricing read, how it spread, and the confidence range) and exactly 3 distinct, concrete
`recommendations` the founder can act on next week.

Rules:
- Describe the adoption path from `rounds` and the overall direction exactly as `headline.trend`;
  an event's delta is its immediate effect, not the final outcome.
- `price.stated_max_price_quartiles` are descriptive quartiles, not recommended prices; judge any
  price only by its `share_willing`.
- Every number must come from the input. Never introduce durations, discounts, guarantees or
  targets that are not in the input; describe such actions without a figure.
- Shares describe what was observed. Never present them as targets, audiences to convert, or
  amounts an action will remove.
- Respondents are simulated personas: never name individuals or suggest contacting them.
- Call the confidence range wide when `confidence.ci_width` exceeds 0.2.
- Write complete text: no placeholders, ellipses, "truncated" markers, or empty strings."""


def _willing_at(price: PriceCurve, amount: float) -> float | None:
    """Share willing at `amount`, read from the step curve (first grid point at or above it)."""
    prices = [p.price for p in price.points]
    i = bisect_left(prices, amount)
    return price.points[i].share_willing if i < len(prices) else None


def _price(price: PriceCurve) -> dict[str, object]:
    data = price.model_dump(exclude={"points", "suggested_tiers"})
    data["stated_max_price_quartiles"] = [
        {"price": t, "share_willing": _willing_at(price, t)} for t in price.suggested_tiers
    ]
    return data


def _spread(spread: SpreadStat) -> dict[str, object]:
    # Self-describing keys; influencers stay anonymous because personas are simulated.
    return {
        "organic_adopters": spread.organic_adopters,
        "influenced_adopters": spread.influenced_adopters,
        "influenced_share_of_adopters": spread.influenced_share,
        "influenced_adopters_reached_by_channel_post": spread.channel_touched_share,
        "top_influencer_conversions_credited": [
            i.conversions_credited for i in spread.top_influencers[:_TOP_INFLUENCERS]
        ],
    }


def _compact(  # noqa: PLR0913
    *,
    headline: Headline,
    curve: Sequence[RoundPoint],
    segments: list[SegmentStat],
    price: PriceCurve,
    objections: list[ObjectionTheme],
    events: list[EventImpact],
    spread: SpreadStat,
    confidence: Confidence,
) -> dict[str, object]:
    strong = [s for s in segments if not s.low_n]
    return {
        "headline": headline.model_dump(),
        "rounds": [p.model_dump(exclude={"event"}) for p in curve],
        "top_segments": [s.model_dump(exclude={"low_n"}) for s in strong[:5]],
        "weak_segments": [s.model_dump(exclude={"low_n"}) for s in strong[-3:]],
        "price": _price(price),
        "objections": [o.model_dump(exclude={"quotes"}) for o in objections[:5]],
        "events": [e.model_dump() for e in events],
        "spread": _spread(spread),
        "confidence": confidence.model_dump(exclude={"cache_hit_ratio"})
        | {"ci_width": round(confidence.adoption_ci_high - confidence.adoption_ci_low, 4)},
    }


async def write_narrative(  # noqa: PLR0913
    client: ChatClient,
    *,
    name: str,
    headline: Headline,
    curve: Sequence[RoundPoint],
    segments: list[SegmentStat],
    price: PriceCurve,
    objections: list[ObjectionTheme],
    events: list[EventImpact],
    spread: SpreadStat,
    confidence: Confidence,
    seed: int,
) -> Narrative:
    stats = json.dumps(
        _compact(
            headline=headline,
            curve=curve,
            segments=segments,
            price=price,
            objections=objections,
            events=events,
            spread=spread,
            confidence=confidence,
        ),
        separators=(",", ":"),
    )
    return await client.complete_json(
        system=_SYSTEM,
        user=_USER.format(name=name, stats=stats),
        schema=Narrative,
        temperature=0.3,
        seed=seed,
    )
