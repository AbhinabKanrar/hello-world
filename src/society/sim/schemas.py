"""Typed contracts for the simulation layer."""
 
from __future__ import annotations
 
import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator
 
from society.errors import SpecError
from society.schemas import StrictModel
 
# ----------------------------------------------------------------- scenario
 
 
class Price(StrictModel):
    amount: float = Field(ge=0)
    period: Literal["one-time", "month", "year"] = "month"
    currency: str = Field("USD", min_length=3, max_length=3)
 
    def render(self) -> str:
        suffix = "" if self.period == "one-time" else f"/{self.period}"
        return f"{self.amount:g} {self.currency}{suffix}"
 
 
class EventKind(StrEnum):
    PRICE_CHANGE = "price_change"
    NEWS = "news"
    COMPETITOR = "competitor"
    PROMOTION = "promotion"
    OUTAGE = "outage"
 
 
class ScenarioEvent(StrictModel):
    round: int = Field(ge=1)
    kind: EventKind
    detail: str = Field(min_length=5, max_length=400)

class ScenarioSpec(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    product: str = Field(min_length=10, max_length=1_000)
    pitch: str = Field(min_length=5, max_length=600)
    price: Price
    rounds: int = Field(5, ge=0, le=52, description="Influence rounds after exposure.")
    events:tuple[ScenarioEvent, ...] = ()
    max_peer_messages: int = Field(6, ge=1, le=20)
    max_channel_posts: int = Field(3, ge=0, le=10)
    broadcast_top_k: int = Field(5, ge=0, le=50, description="Top sharers by influence hit channels.")
    decay_every: int = Field(2, ge=1, description="Idle rounds before interest drops a notch.")

    @model_validator(mode="after")
    def _events_in_range(self) -> Self:
        if any(e.round > self.rounds for e in self.events):
            raise ValueError("event round exceeds scenario rounds")
        return self
 
    def events_at(self, rnd: int) -> tuple[ScenarioEvent, ...]:
        return tuple(e for e in self.events if e.round == rnd)
 
    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]
 
    @classmethod
    def from_yaml(cls, path: Path) -> ScenarioSpec:
        try:
            with path.open("rb") as fh:
                return cls.model_validate(yaml.safe_load(fh))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise SpecError(f"invalid scenario spec {path}: {exc}") from exc


# ------------------------------------------------------------ LLM output


class Reaction(StrictModel):
    """What the model must return. Kept tight so small local models comply."""
 
    interest: int = Field(ge=1, le=5)
    purchase_intent: int = Field(ge=1, le=5)
    max_price: float = Field(ge=0, description="Most they'd pay per period; 0 = would not pay.")
    top_objection: str = Field(min_length=2, max_length=200)
    would_share: bool
    share_message: str = Field("", max_length=280, description="What they'd tell others; empty if not sharing.")
    stance: str = Field(min_length=5, max_length=200, description="One-line summary of current view.")
    reasoning: str = Field(min_length=10, max_length=600)


# -------------------------------------------------------------- outputs

Trigger = Literal["exposure", "influence", "decay"]


class SimEvent(StrictModel):
    """Flat, one row per (round, persona). Columnar-friendly for the aggregator."""
 
    round: int = Field(ge=0)
    index: int = Field(ge=0)
    persona_id: str
    trigger: Trigger
    interest: int
    purchase_intent: int
    max_price: float
    would_share: bool
    top_objection: str
    share_message: str
    stance: str
    reasoning: str
    peer_msgs: int = 0
    channel_msgs: int = 0
    events: int = 0
 
 
class Checkpoint(StrictModel):
    scenario_hash: str
    seed: int
    completed_round: int
    interest: list[int]
    purchase_intent: list[int]
    max_price: list[float]
    would_share: list[bool]
    updated_round: list[int]
    top_objection: list[str]
    share_message: list[str]
    stance: list[str]
 
 
class RoundStats(StrictModel):
    round: int
    llm_calls: int
    decayed: int
    cache_hits: int
    adoption: float = Field(description="Share with purchase_intent >= 4.")
    mean_interest: float
 
 
class SimManifest(StrictModel):
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scenario: str
    scenario_hash: str
    seed: int
    size: int
    rounds: int
    resumed_from: int | None
    chat_model: str
    prompt_tokens: int
    completion_tokens: int
    per_round: list[RoundStats]
