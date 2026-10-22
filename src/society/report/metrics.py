"""Pure NumPy metrics. Every function is O(n) or O(n log n) and allocation-light."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

from society.report.frame import ADOPT_THRESHOLD, Frame
from society.report.schemas import (
    Confidence,
    EventImpact,
    Headline,
    PriceCurve,
    PricePoint,
    RoundPoint,
    SegmentStat,
)
from society.schemas import Persona
from society.sim.schemas import ScenarioSpec

_VERDICT: Final = ((0.35, "strong"), (0.20, "promising"), (0.08, "weak"))
_NUMERIC_BINS: Final = 4
_MIN_SEGMENT_N: Final = 10
_NOTABLE_DELTA: Final = 0.02
_BOOTSTRAP: Final = 4_000

# ------------------------------------------------------------------ curve


def adoption_curve(frame: Frame, scenario: ScenarioSpec) -> list[RoundPoint]:
    adoption = (frame.intent >= ADOPT_THRESHOLD).mean(axis=1)
    interest = frame.interest.mean(axis=1)
    sharers = frame.share.sum(axis=1)
    labels = {e.round: f"{e.kind.value}: {e.detail}" for e in scenario.events}
    return [
        RoundPoint(
            round=r,
            adoption=round(float(adoption[r]), 4),
            mean_interest=round(float(interest[r]), 3),
            sharers=int(sharers[r]),
            event=labels.get(r),
        )
        for r in range(frame.rounds + 1)
    ]


def headline(curve: Sequence[RoundPoint]) -> Headline:
    ad = np.fromiter((p.adoption for p in curve), np.float64, len(curve))
    peak = int(ad.argmax())
    final = float(ad[-1])
    verdict = next((v for t, v in _VERDICT if final >= t), "dead")
    if len(ad) < 2:
        trend = "stable"
    else:
        slope = final - float(ad[max(0, len(ad) - 3)])
        trend = "rising" if slope > 0.01 else "fading" if slope < -0.01 else "stable"
    return Headline(
        final_adoption=round(final, 4),
        peak_adoption=round(float(ad[peak]), 4),
        peak_round=peak,
        trend=trend,
        verdict=verdict,
    )  # type: ignore[arg-type]


# --------------------------------------------------------------- segments


def _numeric_buckets(x: NDArray[np.float64]) -> NDArray[np.object_]:
    edges = np.unique(np.quantile(x, np.linspace(0, 1, _NUMERIC_BINS + 1)))
    if edges.size < 3:
        return np.asarray([f"{x.min():g}–{x.max():g}"] * x.size, dtype=object)
    b = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, edges.size - 2)
    names = np.asarray(
        [f"{edges[k]:g}–{edges[k + 1]:g}" for k in range(edges.size - 1)], dtype=object
    )
    return names[b]


def dimension_labels(
    personas: Sequence[Persona],
) -> Iterator[tuple[str, NDArray[np.int64], NDArray[np.object_]]]:
    """Yield (dimension, persona indices, labels). List attributes expand to multi-membership."""
    n = len(personas)
    all_idx = np.arange(n)
    for key in personas[0].attributes:
        vals = [p.attributes.get(key) for p in personas]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            yield key, all_idx, _numeric_buckets(np.asarray(vals, np.float64))
        elif all(isinstance(v, list) for v in vals):
            idx = np.repeat(all_idx, [len(v) for v in vals])  # type: ignore[arg-type]
            yield key, idx, np.asarray([str(s) for v in vals for s in v], dtype=object)  # type: ignore[union-attr]
        else:
            yield key, all_idx, np.asarray([str(v) for v in vals], dtype=object)
    yield (
        "decision_style",
        all_idx,
        np.asarray([p.traits.decision_style.value for p in personas], dtype=object),
    )
    yield "segment", all_idx, np.asarray([p.traits.segment.value for p in personas], dtype=object)
    yield (
        "price_sensitivity",
        all_idx,
        np.asarray(
            [
                "low (1-2)"
                if p.traits.price_sensitivity <= 2
                else "high (4-5)"
                if p.traits.price_sensitivity >= 4
                else "mid (3)"
                for p in personas
            ],
            dtype=object,
        ),
    )


def segment_stats(frame: Frame, personas: Sequence[Persona]) -> list[SegmentStat]:
    adopted = frame.adopted.astype(np.float64)
    intent = frame.intent[-1].astype(np.float64)
    base = adopted.mean()
    out: list[SegmentStat] = []
    for dim, idx, labels in dimension_labels(personas):
        uniq, inv = np.unique(labels, return_inverse=True)
        cnt = np.bincount(inv, minlength=uniq.size)
        ad = np.bincount(inv, weights=adopted[idx], minlength=uniq.size)
        it = np.bincount(inv, weights=intent[idx], minlength=uniq.size)
        for k, bucket in enumerate(uniq):
            a = ad[k] / cnt[k]
            out.append(
                SegmentStat(
                    dimension=dim,
                    bucket=str(bucket),
                    n=int(cnt[k]),
                    adoption=round(float(a), 4),
                    mean_intent=round(float(it[k] / cnt[k]), 3),
                    lift=round(float(a / base), 3) if base > 0 else 0.0,
                    low_n=bool(cnt[k] < _MIN_SEGMENT_N),
                )
            )
    out.sort(key=lambda s: (s.low_n, -s.lift, -s.n))
    return out


# ------------------------------------------------------------------ price


def price_curve(frame: Frame, list_price: float, *, max_points: int = 40) -> PriceCurve:
    mp = frame.max_price[-1].astype(np.float64)
    n = mp.size
    pos = np.sort(mp[mp > 0])
    willing_at = lambda p: float(n - np.searchsorted(pos, p, side="left")) / n  # noqa: E731
    if pos.size == 0:
        return PriceCurve(
            points=[],
            share_unwilling=1.0,
            median_max_price=0.0,
            list_price=list_price,
            list_price_share=0.0,
            revenue_max_price=None,
            revenue_max_share=None,
            suggested_tiers=[],
        )
    grid = np.unique(np.round(np.quantile(pos, np.linspace(0, 1, max_points)), 2))
    share = (n - np.searchsorted(pos, grid, side="left")) / n
    rev = grid * share
    b = int(rev.argmax())
    tiers = np.unique(np.round(np.quantile(pos, [0.25, 0.5, 0.75]), 2))
    return PriceCurve(
        points=[
            PricePoint(
                price=float(p), share_willing=round(float(s), 4), revenue_index=round(float(r), 4)
            )
            for p, s, r in zip(grid, share, rev, strict=True)
        ],
        share_unwilling=round(1 - pos.size / n, 4),
        median_max_price=round(float(np.median(pos)), 2),
        list_price=list_price,
        list_price_share=round(willing_at(list_price), 4),
        revenue_max_price=float(grid[b]),
        revenue_max_share=round(float(share[b]), 4),
        suggested_tiers=tiers.tolist(),
    )


# ----------------------------------------------------------------- events


def event_impacts(curve: Sequence[RoundPoint], scenario: ScenarioSpec) -> list[EventImpact]:
    if len(curve) < 2 or not scenario.events:
        return []
    ad = np.fromiter((p.adoption for p in curve), np.float64, len(curve))
    mi = np.fromiter((p.mean_interest for p in curve), np.float64, len(curve))
    d_ad, d_mi = np.diff(ad), np.diff(mi)
    ev_rounds = {e.round for e in scenario.events}
    quiet = [r - 1 for r in range(1, len(curve)) if r not in ev_rounds]
    drift = float(d_ad[quiet].mean()) if quiet else 0.0
    return [
        EventImpact(
            round=e.round,
            kind=e.kind.value,
            detail=e.detail,
            delta_adoption=round(float(d_ad[e.round - 1]), 4),
            delta_interest=round(float(d_mi[e.round - 1]), 3),
            baseline_drift=round(drift, 4),
            notable=abs(float(d_ad[e.round - 1]) - drift) >= _NOTABLE_DELTA,
        )
        for e in scenario.events
    ]


# ------------------------------------------------------------- confidence


def confidence(frame: Frame, *, seed: int, level: float = 0.95) -> Confidence:
    """Adoption is a Bernoulli mean → the bootstrap is exactly Binomial(n, p)/n. Vectorised."""
    n, p = frame.n, float(frame.adopted.mean())
    rng = np.random.default_rng(seed)
    draws = rng.binomial(n, p, size=_BOOTSTRAP) / n
    lo, hi = np.quantile(draws, [(1 - level) / 2, 1 - (1 - level) / 2])
    return Confidence(
        n=n,
        rounds=frame.rounds,
        ci_level=level,
        adoption_ci_low=round(float(lo), 4),
        adoption_ci_high=round(float(hi), 4),
        cache_hit_ratio=frame.cache_hit_ratio,
    )
