"""Typed contracts for the simulation layer."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, create_model, model_validator

from society.errors import SpecError
from society.schemas import StrictModel

# ----------------------------------------------------------------- scenario


class Price(StrictModel):
    amount: float = Field(ge=0, allow_inf_nan=False)
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
    new_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_price_payload(self) -> Self:
        if self.kind is EventKind.PRICE_CHANGE:
            if self.new_price is None:
                raise ValueError("price_change requires a numeric new_price")
        elif self.new_price is not None:
            raise ValueError("new_price is only valid for price_change events")
        return self


class ScenarioSpec(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    product: str = Field(min_length=10, max_length=1_000)
    pitch: str = Field(min_length=5, max_length=600)
    price: Price
    rounds: int = Field(5, ge=0, le=52, description="Influence rounds after exposure.")
    events: tuple[ScenarioEvent, ...] = ()
    max_peer_messages: int = Field(6, ge=1, le=20)
    max_channel_posts: int = Field(3, ge=0, le=10)
    broadcast_top_k: int = Field(
        5, ge=0, le=50, description="Top sharers by influence hit channels."
    )
    decay_every: int = Field(2, ge=1, description="Idle rounds before interest drops a notch.")

    @model_validator(mode="after")
    def _events_in_range(self) -> Self:
        price_rounds: set[int] = set()

        for event in self.events:
            if event.round > self.rounds:
                raise ValueError("event round exceeds scenario rounds")
            if event.kind is EventKind.PRICE_CHANGE:
                if event.round in price_rounds:
                    raise ValueError("only one price_change is allowed per round")
                price_rounds.add(event.round)

        return self

    def price_at(self, rnd: int) -> Price:
        """Effective price after applying all price changes through this round."""
        if not 0 <= rnd <= self.rounds:
            raise ValueError("round is outside the scenario")

        amount = self.price.amount
        latest_round = -1

        for event in self.events:
            if (
                event.kind is EventKind.PRICE_CHANGE
                and latest_round < event.round <= rnd
            ):
                if event.new_price is None:
                    raise ValueError("price_change is missing new_price")
                amount = event.new_price
                latest_round = event.round

        return Price(
            amount=amount,
            period=self.price.period,
            currency=self.price.currency,
        )

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
    max_price: float = Field(ge=0, allow_inf_nan=False, description="Most they'd pay per period; 0 = would not pay.")
    top_objection: str = Field(min_length=2, max_length=200)
    would_share: bool
    share_message: str = Field(
        "", max_length=280, description="What they'd tell others; empty if not sharing."
    )
    stance: str = Field(
        min_length=5, max_length=200, description="One-line summary of current view."
    )
    reasoning: str = Field(min_length=10, max_length=600)

    @model_validator(mode="after")
    def _validate_sharing(self) -> Self:
        if self.would_share and not self.share_message:
            raise ValueError("would_share=true requires a non-empty share_message")
        if not self.would_share and self.share_message:
            raise ValueError("would_share=false requires an empty share_message")
        return self

# -------------------------------------------------------------- outputs

Trigger = Literal["exposure", "influence", "decay"]


class SimEvent(StrictModel):
    """Flat, one row per (round, persona). Columnar-friendly for the aggregator."""

    round: int = Field(ge=0)
    index: int = Field(ge=0)
    persona_id: str
    trigger: Trigger
    interest: int = Field(ge=1, le=5)
    purchase_intent: int = Field(ge=1, le=5)
    max_price: float = Field(ge=0, allow_inf_nan=False)
    would_share: bool
    top_objection: str
    share_message: str
    stance: str
    reasoning: str
    peer_msgs: int = Field(default=0, ge=0)
    channel_msgs: int = Field(default=0, ge=0)
    events: int = Field(default=0, ge=0)


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


class TrialOption(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=200)
    group: str | None = Field(default=None, min_length=1, max_length=100)
    nonresponse: bool = False

    @model_validator(mode="after")
    def _validate_group(self) -> Self:
        if self.nonresponse and self.group is not None:
            raise ValueError("nonresponse options cannot belong to acceptance groups")
        return self


class TrialScenarioSpec(StrictModel):
    schema_version: Literal["trial-v1"] = "trial-v1"
    name: str = Field(min_length=2, max_length=120)
    stimulus: str = Field(min_length=1, max_length=10_000)
    question: str = Field(min_length=1, max_length=2_000)
    options: tuple[TrialOption, ...] = Field(min_length=2, max_length=12)
    as_of: date | None = None

    @model_validator(mode="after")
    def _validate_options(self) -> Self:
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("response option IDs must be unique")
        if len({option.label for option in self.options}) != len(self.options):
            raise ValueError("response option labels must be unique")
        if sum(not option.nonresponse for option in self.options) < 2:
            raise ValueError("at least two substantive response options are required")
        return self

    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_yaml(cls, path: Path) -> TrialScenarioSpec:
        try:
            with path.open("rb") as fh:
                return cls.model_validate(yaml.safe_load(fh))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise SpecError(f"invalid trial scenario {path}: {exc}") from exc


class TrialAnswer(StrictModel):
    option_index: int = Field(ge=0, strict=True)
    reason: str | None = Field(min_length=1, max_length=600)
    concern: str | None = Field(min_length=1, max_length=400)
    information_needed: str | None = Field(min_length=1, max_length=400)
    change_condition: str | None = Field(min_length=1, max_length=400)


def trial_answer_schema(option_count: int) -> type[TrialAnswer]:
    if not 2 <= option_count <= 12:
        raise ValueError("option_count must be between 2 and 12")
    return create_model(
        "ConfiguredTrialAnswer",
        __base__=TrialAnswer,
        option_index=(
            int,
            Field(ge=0, lt=option_count, strict=True),
        ),
    )


class TrialRecord(StrictModel):
    index: int = Field(ge=0, strict=True)
    persona_id: str
    status: Literal["answered", "technical_failure"]
    answer: TrialAnswer | None

    @model_validator(mode="after")
    def _validate_status(self) -> Self:
        if (self.status == "answered") != (self.answer is not None):
            raise ValueError("only answered records may contain an answer")
        return self
