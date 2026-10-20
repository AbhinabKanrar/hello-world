"""Layer 1A — seeded, vectorised attribute + trait sampling. Zero LLM calls.

Guarantee: identical (spec, seed) → byte-identical population.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from society.schemas import (
    AttributeSpec,
    AttrValue,
    AudienceSpec,
    Categorical,
    DecisionStyle,
    Diversity,
    NumericRange,
    Persona,
    Segment,
    Traits,
)

# Diversity → std-dev of ordinal traits; wider = more personality spread.
_TRAIT_STD = {Diversity.LOW: 0.6, Diversity.MEDIUM: 0.9, Diversity.HIGH: 1.2}
# Diversity → how many std-devs the range spans for `normal` attributes.
_RANGE_SIGMAS = {Diversity.LOW: 6.0, Diversity.MEDIUM: 5.0, Diversity.HIGH: 4.0}
_DECISION_STYLES = tuple(DecisionStyle)
_DECISION_P = np.array([0.25, 0.35, 0.30, 0.10])
_PARETO_SHAPE = 2.0  # heavy tail → a few influencers, many followers


class PopulationSampler:
    __slots__ = ("_rng", "_spec")

    def __init__(self, spec: AudienceSpec, seed: int) -> None:
        self._spec = spec
        self._rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ API
    def sample(self) -> list[Persona]:
        n = self._spec.size
        columns = {name: self._sample_attribute(s, n) for name, s in self._spec.attributes.items()}
        traits = self._sample_traits(n)
        return [
            Persona(
                id=f"p_{i:05d}",
                index=i,
                attributes={k: col[i] for k, col in columns.items()},
                traits=traits[i],
            )
            for i in range(n)
        ]

    # ------------------------------------------------------------ attributes
    def _sample_attribute(self, spec: AttributeSpec, n: int) -> list[AttrValue]:
        if isinstance(spec, NumericRange):
            return self._sample_numeric(spec, n)
        return self._sample_categorical(spec, n)

    def _sample_numeric(self, spec: NumericRange, n: int) -> list[AttrValue]:
        if spec.distribution == "uniform":
            values = self._rng.uniform(spec.lo, spec.hi, n)
        else:
            mean = (spec.lo + spec.hi) / 2
            std = max((spec.hi - spec.lo) / _RANGE_SIGMAS[self._spec.diversity], 1e-9)
            values = np.clip(self._rng.normal(mean, std, n), spec.lo, spec.hi)
        if spec.integer:
            # +0.5 shift keeps endpoints equiprobable under uniform sampling.
            return np.clip(np.floor(values + 0.5), spec.lo, spec.hi).astype(np.int64).tolist()
        return np.round(values, 2).tolist()

    def _sample_categorical(self, spec: Categorical, n: int) -> list[AttrValue]:
        opts = np.asarray(spec.options, dtype=object)
        p = np.asarray(spec.weights, dtype=np.float64) if spec.weights else None
        if p is not None:
            p = p / p.sum()
        if spec.pick == 1:
            return self._rng.choice(opts, size=n, p=p).tolist()
        lo, hi = (spec.pick, spec.pick) if isinstance(spec.pick, int) else spec.pick
        counts = self._rng.integers(lo, hi + 1, size=n)
        return [
            self._rng.choice(opts, size=int(k), replace=False, p=p).tolist()  # type: ignore[misc]
            for k in counts
        ]

    # ---------------------------------------------------------------- traits
    def _sample_traits(self, n: int) -> list[Traits]:
        std = _TRAIT_STD[self._spec.diversity]
        rng = self._rng

        def ordinal(shift: NDArray[np.int64] | int = 0) -> NDArray[np.int64]:
            return np.clip(np.rint(rng.normal(3.0, std, n)) + shift, 1, 5).astype(np.int64)

        non_buyers = np.zeros(n, dtype=bool)
        k = round(n * self._spec.non_buyer_share)
        if k:
            non_buyers[rng.choice(n, size=k, replace=False)] = True
        shift = non_buyers.astype(np.int64)

        openness = ordinal(-shift)
        skepticism = ordinal(shift)
        price_sens = ordinal()
        influence = 1.0 - np.exp(-rng.pareto(_PARETO_SHAPE, n))  # maps heavy tail into [0, 1)
        styles = rng.choice(len(_DECISION_STYLES), size=n, p=_DECISION_P)

        return [
            Traits(
                openness=int(openness[i]),
                price_sensitivity=int(price_sens[i]),
                skepticism=int(skepticism[i]),
                influence=float(round(influence[i], 4)),
                decision_style=_DECISION_STYLES[styles[i]],
                segment=Segment.NON_BUYER if non_buyers[i] else Segment.PROSPECT,
            )
            for i in range(n)
        ]
