"""Typed report contracts. `Report` is the machine-readable deliverable; Markdown is derived from it."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Final, Literal

from pydantic import Field, field_validator

from society.schemas import StrictModel

Verdict = Literal["strong", "promising", "weak", "dead"]
Trend = Literal["rising", "stable", "fading"]

# Looser than the prompt's 120-200 words so near-miss answers are not rejected.
NARRATIVE_MIN_WORDS: Final = 100
NARRATIVE_MAX_WORDS: Final = 250
NARRATIVE_RECOMMENDATIONS: Final = 3
_PLACEHOLDER: Final = re.compile(r"\.{3}|…|\(truncated\)|\bTBD\b|\bTODO\b", re.IGNORECASE)

Recommendation = Annotated[str, Field(min_length=20, max_length=300)]


def _reject_placeholder(value: str, field: str) -> str:
    if _PLACEHOLDER.search(value):
        raise ValueError(f"{field} contains placeholder text; write the complete content")
    return value


class RoundPoint(StrictModel):
    round: int
    adoption: float
    mean_interest: float
    sharers: int
    event: str | None = None


class Headline(StrictModel):
    final_adoption: float
    peak_adoption: float
    peak_round: int
    trend: Trend
    verdict: Verdict


class SegmentStat(StrictModel):
    dimension: str
    bucket: str
    n: int
    adoption: float
    mean_intent: float
    lift: float = Field(description="segment adoption / population adoption")
    low_n: bool


class PricePoint(StrictModel):
    price: float
    share_willing: float
    revenue_index: float = Field(description="price × share_willing (relative, not currency)")


class PriceCurve(StrictModel):
    points: list[PricePoint]
    share_unwilling: float
    median_max_price: float
    list_price: float
    list_price_share: float
    revenue_max_price: float | None
    revenue_max_share: float | None
    suggested_tiers: list[float]


class ObjectionTheme(StrictModel):
    label: str
    count: int
    share: float
    quotes: list[str]
    top_segments: list[str]


class Influencer(StrictModel):
    index: int
    persona_id: str
    name: str
    influence: float
    in_degree: int
    conversions_credited: float


class SpreadStat(StrictModel):
    organic_adopters: int
    influenced_adopters: int
    influenced_share: float
    channel_touched_share: float
    top_influencers: list[Influencer]


class EventImpact(StrictModel):
    round: int
    kind: str
    detail: str
    delta_adoption: float
    delta_interest: float
    baseline_drift: float
    notable: bool


class Quote(StrictModel):
    persona_id: str
    name: str
    segment: str
    purchase_intent: int
    text: str


class Confidence(StrictModel):
    n: int
    rounds: int
    ci_level: float
    adoption_ci_low: float
    adoption_ci_high: float
    cache_hit_ratio: float | None


class Narrative(StrictModel):
    """Validation errors are fed back to the model, so messages must say how to fix the output."""

    summary: str = Field(min_length=50, max_length=2_000)
    recommendations: list[Recommendation] = Field(
        min_length=NARRATIVE_RECOMMENDATIONS, max_length=NARRATIVE_RECOMMENDATIONS
    )

    @field_validator("summary")
    @classmethod
    def _complete_summary(cls, value: str) -> str:
        words = len(value.split())
        if not NARRATIVE_MIN_WORDS <= words <= NARRATIVE_MAX_WORDS:
            raise ValueError(
                f"summary must be {NARRATIVE_MIN_WORDS}-{NARRATIVE_MAX_WORDS} words, got {words}"
            )
        return _reject_placeholder(value, "summary")

    @field_validator("recommendations")
    @classmethod
    def _complete_recommendations(cls, value: list[str]) -> list[str]:
        for item in value:
            _reject_placeholder(item, "recommendation")
        if len({item.casefold() for item in value}) != len(value):
            raise ValueError("recommendations must be distinct")
        return value


class Report(StrictModel):
    scenario: str
    scenario_hash: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    headline: Headline
    curve: list[RoundPoint]
    segments: list[SegmentStat]
    price: PriceCurve
    objections: list[ObjectionTheme]
    spread: SpreadStat
    events: list[EventImpact]
    voices: list[Quote]
    confidence: Confidence
    narrative: Narrative | None = None


class TrialCount(StrictModel):
    id: str
    label: str
    count: int = Field(ge=0)
    nonresponse: bool = False
    percent_completed: float | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )
    percent_valid: float | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )
    reason_examples: tuple[str, ...] = ()


class TrialReport(StrictModel):
    schema_version: Literal["trial-report-v1"] = "trial-report-v1"
    scenario: str
    scenario_hash: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requested: int = Field(ge=1)
    completed: int = Field(ge=0)
    valid: int = Field(ge=0)
    nonresponse: int = Field(ge=0)
    technical_failures: int = Field(ge=0)
    categories: tuple[TrialCount, ...]
    groups: tuple[TrialCount, ...]
