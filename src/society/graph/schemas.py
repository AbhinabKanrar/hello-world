"""Typed contracts for the social graph layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from society.schemas import StrictModel


class GraphConfig(StrictModel):
    """Topology knobs. Defaults produce a realistic small-world network for 50-100k personas."""

    mean_degree: int = Field(8, ge=1, le=200, description="Poisson mean of out-degree.")
    min_degree: int = Field(2, ge=0)
    max_degree: int = Field(64, ge=1)
    rewire_prob: float = Field(0.1, ge=0.0, le=1.0, description="Share of long-range random ties.")
    homophily_beta: float = Field(4.0, ge=0.0, description="Similarity → tie-likelihood sharpness.")
    influence_alpha: float = Field(2.0, ge=0.0, description="Preferential attachment to hubs.")
    trust_base: float = Field(0.3, ge=0.0, le=1.0)
    trust_similarity: float = Field(0.4, ge=0.0, le=1.0)
    trust_influence: float = Field(0.3, ge=0.0, le=1.0)
    skepticism_discount: float = Field(
        0.1, ge=0.0, le=0.25, description="Trust −x per skepticism pt."
    )
    geo_min_members: int = Field(3, ge=2)

    @model_validator(mode="after")
    def _degree_order(self) -> Self:
        if not self.min_degree <= self.mean_degree <= self.max_degree:
            raise ValueError("require min_degree <= mean_degree <= max_degree")
        return self


class Channel(StrictModel):
    id: str = Field(pattern=r"^(interest|geo):[a-z0-9\-]+$")
    name: str
    kind: Literal["interest", "geo"]
    members: list[int]


class AdjacencyRow(StrictModel):
    """One persona's out-edges. Short keys keep 100k-row files small."""

    i: int = Field(ge=0)
    to: list[int]
    w: list[float]
    ch: list[str]

    @model_validator(mode="after")
    def _aligned(self) -> Self:
        if len(self.to) != len(self.w):
            raise ValueError("to/w length mismatch")
        return self


class GraphManifest(StrictModel):
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    seed: int
    size: int
    edges: int
    mean_out_degree: float
    max_in_degree: int
    homophily_lift: float = Field(description="mean edge similarity / mean random-pair similarity")
    channels: int
    config: GraphConfig
