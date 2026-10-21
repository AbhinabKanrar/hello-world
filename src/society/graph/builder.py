"""Layer 2 — homophily-weighted small-world graph with influence hubs and channels.
 
Complexity: O(n² / block) time via BLAS, O(block x n) memory. Zero LLM calls.
Sampling without replacement uses the Gumbel-top-k trick: adding Gumbel noise to
log-weights and taking the top-k is an exact sample ∝ weights — fully vectorised.
"""

from __future__ import annotations
 
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
 
import numpy as np
from numpy.typing import NDArray
 
from society.graph.model import SocialGraph, slugify
from society.graph.schemas import Channel, GraphConfig, GraphManifest
from society.graph.similarity import FeatureEncoder, l2_normalize
from society.schemas import DecisionStyle, Persona


_log = logging.getLogger(__name__)
 
_STYLES: Final = tuple(DecisionStyle)
_STYLE_INDEX: Final = {s: i for i, s in enumerate(_STYLES)}
_TRUST_MIN: Final = 0.05
_SIM_BLOCK_BUDGET_BYTES: Final = 64 << 20  # per b×n float32 matrix (we hold ~3)
_BASELINE_PAIRS: Final = 8_192
 
# P(member | decision_style). Interest channels are broadcast nodes the engine posts to.
_INTEREST_CHANNELS: Final[dict[str, dict[DecisionStyle, float]]] = {
    "friends-circle": {
        DecisionStyle.ASKS_FRIENDS: 0.90,
        DecisionStyle.IMPULSIVE: 0.50,
        DecisionStyle.RESEARCHER: 0.40,
        DecisionStyle.LOYALIST: 0.40,
    },
    "online-reviews": {
        DecisionStyle.RESEARCHER: 0.90,
        DecisionStyle.ASKS_FRIENDS: 0.40,
        DecisionStyle.IMPULSIVE: 0.30,
        DecisionStyle.LOYALIST: 0.20,
    },
    "social-feed": {
        DecisionStyle.IMPULSIVE: 0.80,
        DecisionStyle.ASKS_FRIENDS: 0.60,
        DecisionStyle.RESEARCHER: 0.50,
        DecisionStyle.LOYALIST: 0.30,
    },
    "mainstream-news": {
        DecisionStyle.LOYALIST: 0.70,
        DecisionStyle.RESEARCHER: 0.50,
        DecisionStyle.ASKS_FRIENDS: 0.30,
        DecisionStyle.IMPULSIVE: 0.30,
    },
}

@dataclass(frozen=True, slots=True)
class GraphBuildResult:
    graph: SocialGraph
    manifest: GraphManifest
 
 
def _block_rows(n: int) -> int:
    return max(1, min(2048, _SIM_BLOCK_BUDGET_BYTES // max(n * 4, 1)))

class GraphBuilder:
    __slots__ = ("_cfg", "_seed")
 
    def __init__(self, config: GraphConfig | None = None, *, seed: int) -> None:
        self._cfg = config or GraphConfig()
        self._seed = seed
 
    # ------------------------------------------------------------------ API
    def build(self, personas: Sequence[Persona]) -> GraphBuildResult:
        n = len(personas)
        rng = np.random.default_rng(self._seed)
        channels, memberships = self._assign_channels(personas, rng)
 
        if n < 2:
            graph = SocialGraph(
                n, np.zeros(n + 1, np.int64), np.empty(0, np.int32), np.empty(0, np.float32),
                channels, memberships,
            )
            return GraphBuildResult(graph, self._manifest(graph, homophily_lift=1.0))
 
        unit = l2_normalize(FeatureEncoder().transform(personas))
        influence = np.fromiter((p.traits.influence for p in personas), np.float32, n)
        skepticism = np.fromiter((p.traits.skepticism for p in personas), np.float32, n)
        indptr, indices, weights, edge_sim_sum = self._sample_edges(
            unit, influence, skepticism, rng
        )
        graph = SocialGraph(n, indptr, indices, weights, channels, memberships)
 
        baseline = self._baseline_similarity(unit, rng)
        lift = float(edge_sim_sum / max(graph.edges, 1) / max(baseline, 1e-6))
        _log.info("graph_built", extra={"n": n, "edges": graph.edges, "homophily_lift": round(lift, 3)})
        return GraphBuildResult(graph, self._manifest(graph, homophily_lift=lift))
 
    # -------------------------------------------------------------- edges
    def _sample_edges(
        self,
        unit: NDArray[np.float32],
        influence: NDArray[np.float32],
        skepticism: NDArray[np.float32],
        rng: np.random.Generator,
    ) -> tuple[NDArray[np.int64], NDArray[np.int32], NDArray[np.float32], float]:
        cfg, n = self._cfg, unit.shape[0]
        cap = min(cfg.max_degree, n - 1)
        degree = np.clip(rng.poisson(cfg.mean_degree, n), min(cfg.min_degree, cap), cap)
        n_far = np.rint(degree * cfg.rewire_prob).astype(np.int64)
        n_local = degree - n_far
 
        bias = (cfg.influence_alpha * influence)[None, :]
        trust_scale = 1.0 - cfg.skepticism_discount * (skepticism - 3.0)

        idx_chunks: list[NDArray[np.int32]] = []
        w_chunks: list[NDArray[np.float32]] = []
        counts = np.zeros(n, dtype=np.int64)
        edge_sim_sum = 0.0
        block = _block_rows(n)
 
        for start in range(0, n, block):
            stop = min(start + block, n)
            b = stop - start
            rows = np.arange(start, stop)

            sims = unit[start:stop] @ unit.T  # (b, n) cosine, since rows are unit
            keys = cfg.homophily_beta * sims + bias
            keys += rng.gumbel(size=(b, n)).astype(np.float32)
            keys[np.arange(b), rows] = -np.inf  # no self-loops

            # Gumbel-top-k, vectorised over the block.
            kmax = int(n_local[start:stop].max())
            if kmax:
                part = np.argpartition(-keys, kmax - 1, axis=1)[:, :kmax]
                order = np.argsort(-np.take_along_axis(keys, part, axis=1), axis=1)
                local = np.take_along_axis(part, order, axis=1)
            else:
                local = np.empty((b, 0), dtype=np.int64)

            # Long-range shortcuts: uniform over [0, n) \ {self}.
            fmax = int(n_far[start:stop].max())
            far = rng.integers(0, n - 1, size=(b, fmax))
            far += far >= rows[:, None]
 
            for r in range(b):
                i = start + r
                nbrs = np.unique(np.concatenate((local[r, : n_local[i]], far[r, : n_far[i]])))
                s = sims[r, nbrs]
                trust = (
                    cfg.trust_base + cfg.trust_similarity * s + cfg.trust_influence * influence[nbrs]
                ) * trust_scale[i]
                idx_chunks.append(nbrs.astype(np.int32))
                w_chunks.append(np.clip(trust, _TRUST_MIN, 1.0).astype(np.float32))
                counts[i] = nbrs.size
                edge_sim_sum += float(s.sum())

        indptr = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        return indptr, np.concatenate(idx_chunks), np.concatenate(w_chunks), edge_sim_sum
 
    @staticmethod
    def _baseline_similarity(unit: NDArray[np.float32], rng: np.random.Generator) -> float:
        n = unit.shape[0]
        a = rng.integers(0, n, _BASELINE_PAIRS)
        b = rng.integers(0, n - 1, _BASELINE_PAIRS)

        b += b >= a
        return float(np.einsum("ij,ij->i", unit[a], unit[b]).mean())
 
    # ----------------------------------------------------------- channels
    def _assign_channels(
        self, personas: Sequence[Persona], rng: np.random.Generator
    ) -> tuple[tuple[Channel, ...], tuple[tuple[str, ...], ...]]:
        n = len(personas)
        memberships: list[list[str]] = [[] for _ in range(n)]
        channels: list[Channel] = []
 
        def add(channel: Channel) -> None:
            channels.append(channel)
            for m in channel.members:
                memberships[m].append(channel.id)

        if n:
            style_idx = np.fromiter(
                (_STYLE_INDEX[p.traits.decision_style] for p in personas), np.int64, n
            )
            for name, probs in _INTEREST_CHANNELS.items():
                table = np.asarray([probs[s] for s in _STYLES])
                members = np.flatnonzero(rng.random(n) < table[style_idx])
                if members.size:
                    add(Channel(id=f"interest:{name}", name=name, kind="interest", members=members.tolist()))
 
        by_city: dict[str, list[int]] = {}
        for i, p in enumerate(personas):
            if p.profile is not None:
                by_city.setdefault(p.profile.city, []).append(i)
        for city, members in sorted(by_city.items()):
            if len(members) >= self._cfg.geo_min_members:
                add(Channel(id=f"geo:{slugify(city)}", name=city, kind="geo", members=members))
 
        return tuple(channels), tuple(tuple(m) for m in memberships)
 
    # ----------------------------------------------------------- manifest
    def _manifest(self, graph: SocialGraph, *, homophily_lift: float) -> GraphManifest:
        return GraphManifest(
            run_id=uuid.uuid4().hex[:12],
            seed=self._seed,
            size=graph.n,
            edges=graph.edges,
            mean_out_degree=float(graph.edges / graph.n) if graph.n else 0.0,
            max_in_degree=int(graph.in_degrees().max()) if graph.edges else 0,

            homophily_lift=round(homophily_lift, 4),
            channels=len(graph.channels),
            config=self._cfg,
        )
