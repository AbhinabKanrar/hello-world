"""Typed contracts for every boundary: YAML in, LLM out, storage.

Design rules:
  * All models are frozen + extra="forbid" — bad input fails loudly at the edge.
  * Attribute specs are a discriminated union so downstream code never sniffs types.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from society.errors import SpecError

# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #

_RANGE_RE = re.compile(
    r"^\s*(?P<lo>-?\d+(?:\.\d+)?)\s*(?P<lo_suf>[kKmM]?)\s*-\s*"
    r"(?P<hi>-?\d+(?:\.\d+)?)\s*(?P<hi_suf>[kKmM]?)\s*$"
)
_SUFFIX_MULT = {"": 1.0, "k": 1_000.0, "m": 1_000_000.0}

type AttrValue = int | float | str | list[str]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Diversity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecisionStyle(StrEnum):
    IMPULSIVE = "impulsive"
    RESEARCHER = "researcher"
    ASKS_FRIENDS = "asks-friends"
    LOYALIST = "loyalist"


class Segment(StrEnum):
    PROSPECT = "prospect"
    NON_BUYER = "non_buyer"


# --------------------------------------------------------------------------- #
# Attribute specs
# --------------------------------------------------------------------------- #


class NumericRange(_Strict):
    kind: Literal["range"] = "range"
    lo: float
    hi: float
    integer: bool = True
    distribution: Literal["uniform", "normal"] = "uniform"

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.lo > self.hi:
            raise ValueError(f"range lo ({self.lo}) must be <= hi ({self.hi})")
        return self

    @classmethod
    def parse(cls, text: str) -> NumericRange:
        m = _RANGE_RE.match(text)
        if m is None:
            raise ValueError(f"not a range: {text!r}")
        lo = float(m["lo"]) * _SUFFIX_MULT[m["lo_suf"].lower()]
        hi = float(m["hi"]) * _SUFFIX_MULT[m["hi_suf"].lower()]
        return cls(lo=lo, hi=hi, integer="." not in text)


class Categorical(_Strict):
    kind: Literal["categorical"] = "categorical"
    options: tuple[str, ...] = Field(min_length=1)
    weights: tuple[float, ...] | None = None
    pick: int | tuple[int, int] = 1  # exact count, or inclusive (min, max) for multi-select

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        n = len(self.options)
        if self.weights is not None and len(self.weights) != n:
            raise ValueError("weights must align with options")
        lo, hi = (self.pick, self.pick) if isinstance(self.pick, int) else self.pick
        if not 1 <= lo <= hi <= n:
            raise ValueError(f"pick {self.pick} invalid for {n} options")
        return self


AttributeSpec = Annotated[NumericRange | Categorical, Field(discriminator="kind")]


def _coerce_attribute(raw: Any) -> Any:  # noqa: ANN401 - YAML is untyped by nature
    """Translate YAML shorthand into explicit specs; explicit dicts pass through."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return NumericRange.parse(raw)
        except ValueError:
            return Categorical(options=(raw,), pick=1)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return NumericRange(lo=float(raw), hi=float(raw), integer=isinstance(raw, int))
    if isinstance(raw, list):
        opts = tuple(str(o) for o in raw)
        return Categorical(options=opts, pick=(1, min(2, len(opts))))
    raise ValueError(f"unsupported attribute value: {raw!r}")


# --------------------------------------------------------------------------- #
# Audience spec (input)
# --------------------------------------------------------------------------- #


class AudienceSpec(_Strict):
    audience: str = Field(min_length=3, max_length=500)
    size: int = Field(ge=1, le=100_000)
    attributes: dict[str, AttributeSpec] = Field(min_length=1)
    diversity: Diversity = Diversity.HIGH
    non_buyer_share: float = Field(0.25, ge=0.0, le=0.9)

    @field_validator("attributes", mode="before")
    @classmethod
    def _coerce(cls, raw: Any) -> Any:  # noqa: ANN401
        if not isinstance(raw, dict):
            raise ValueError("attributes must be a mapping")
        return {str(k): _coerce_attribute(v) for k, v in raw.items()}

    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]

    @classmethod
    def from_yaml(cls, path: Path) -> AudienceSpec:
        try:
            with path.open("rb") as fh:
                data = yaml.safe_load(fh)
            return cls.model_validate(data)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise SpecError(f"invalid audience spec {path}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Persona (output)
# --------------------------------------------------------------------------- #


class Traits(_Strict):
    """Hidden psychographics injected regardless of user input — prevents 'defining the answer'."""

    openness: int = Field(ge=1, le=5)
    price_sensitivity: int = Field(ge=1, le=5)
    skepticism: int = Field(ge=1, le=5)
    influence: float = Field(ge=0.0, le=1.0)
    decision_style: DecisionStyle
    segment: Segment


class PersonaProfile(_Strict):
    """LLM-authored narrative layer. Kept small so it fits prompts cheaply."""

    name: str = Field(min_length=2, max_length=60)
    city: str = Field(min_length=2, max_length=80)
    bio: str = Field(min_length=40, max_length=900)
    current_solution: str = Field(min_length=5, max_length=300)
    switch_trigger: str = Field(min_length=5, max_length=300)


class Persona(_Strict):
    id: str = Field(pattern=r"^p_\d{5,}$")
    index: int = Field(ge=0)
    attributes: dict[str, AttrValue]
    traits: Traits
    profile: PersonaProfile | None = None

    def with_profile(self, profile: PersonaProfile) -> Persona:
        return self.model_copy(update={"profile": profile})


class RunManifest(_Strict):
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    spec_hash: str
    seed: int
    size: int
    chat_model: str | None
    embed_model: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    regenerated: int = 0
