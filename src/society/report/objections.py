"""Objection themes: normalise → dedupe → embed uniques only → greedy leader clustering.

Dedup first matters: 10k personas typically produce a few hundred distinct objection strings,
so the embedding call and the O(m·k·d) clustering both run on m ≪ n. Leaders are the most
frequent strings, so labels are stable and human-readable. Without a client we fall back to
exact-match grouping — still useful, never crashes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from society.graph.similarity import l2_normalize
from society.llm.base import ChatClient
from society.report.schemas import ObjectionTheme

_WS = re.compile(r"\s+")
_TRAIL = re.compile(r"[.!\s]+$")
_GRAM_BUDGET_BYTES = 64 << 20  # m×m float32; m ≤ ~4k fits


def _norm(s: str) -> str:
    return _TRAIL.sub("", _WS.sub(" ", s.strip().lower()))


def leader_cluster(unit: NDArray[np.float32], threshold: float) -> NDArray[np.int64]:
    """Rows must be unit vectors ordered by priority (first row of a cluster becomes its leader)."""
    m = unit.shape[0]
    labels = np.empty(m, np.int64)
    # leaders = np.empty_like(unit)
    # k = 0
    # for i in range(m):
    #     if k:
    #         sims = leaders[:k] @ unit[i]
    #         j = int(sims.argmax())
    #         if sims[j] >= threshold:
    #             labels[i] = j
    #             continue
    #     leaders[k] = unit[i]
    #     labels[i] = k
    #     k += 1
    # return labels

    lead = np.empty(m, np.int64)  # row index of each cluster's leader
    k = 0

    if m * m * 4 <= _GRAM_BUDGET_BYTES:
        gram = unit @ unit.T  # one BLAS call; loop below is integer indexing only
        for i in range(m):
            if k:
                sims = gram[i, lead[:k]]
                j = int(sims.argmax())
                if sims[j] >= threshold:
                    labels[i] = j
                    continue
            lead[k] = i
            labels[i] = k
            k += 1
        return labels

    for i in range(m):  # streaming fallback for very large m
        if k:
            sims = unit[lead[:k]] @ unit[i]
            j = int(sims.argmax())
            if sims[j] >= threshold:
                labels[i] = j
                continue
        lead[k] = i
        labels[i] = k
        k += 1

    return labels


async def objection_themes(
    texts: Sequence[str],
    persona_labels: Sequence[str],
    client: ChatClient | None,
    *,
    threshold: float = 0.82,
    max_themes: int = 8,
) -> list[ObjectionTheme]:
    n = len(texts)
    if n == 0:
        return []
    normed = np.asarray([_norm(t) for t in texts], dtype=object)
    uniq, first, inv, counts = np.unique(
        normed, return_index=True, return_inverse=True, return_counts=True
    )
    order = np.argsort(-counts, kind="stable")  # most frequent first → becomes leader

    if client is not None and uniq.size > 1:
        emb = l2_normalize(await client.embed([str(uniq[i]) for i in order]))
        cluster_in_order = leader_cluster(emb, threshold)
        cluster_of_unique = np.empty(uniq.size, np.int64)
        cluster_of_unique[order] = cluster_in_order
    else:
        cluster_of_unique = np.empty(uniq.size, np.int64)
        cluster_of_unique[order] = np.arange(uniq.size)

    theme_of_persona = cluster_of_unique[inv]
    k = int(cluster_of_unique.max()) + 1
    theme_counts = np.bincount(theme_of_persona, minlength=k)
    plabels = np.asarray(persona_labels, dtype=object)
    raw = list(texts)

    themes: list[ObjectionTheme] = []
    for t in np.argsort(-theme_counts, kind="stable")[:max_themes].tolist():
        members_u = np.flatnonzero(cluster_of_unique == t)
        members_u = members_u[np.argsort(-counts[members_u], kind="stable")]
        quotes = [raw[int(first[u])].strip() for u in members_u[:3]]
        seg_vals, seg_cnt = np.unique(plabels[theme_of_persona == t], return_counts=True)
        top = np.argsort(-seg_cnt, kind="stable")[:2]
        themes.append(
            ObjectionTheme(
                label=quotes[0],
                count=int(theme_counts[t]),
                share=round(float(theme_counts[t] / n), 4),
                quotes=quotes,
                top_segments=[f"{seg_vals[i]} ({seg_cnt[i]})" for i in top],
            )
        )
    covered = sum(th.count for th in themes)
    if covered < n:
        themes.append(
            ObjectionTheme(
                label="Other",
                count=n - covered,
                share=round((n - covered) / n, 4),
                quotes=[],
                top_segments=[],
            )
        )
    return themes
