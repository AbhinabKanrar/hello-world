"""Who moved the needle: trust-weighted attribution of influence-triggered conversions.
 
A persona converted in round r via influence credits the neighbours it listens to who were
sharing in round r-1, split ∝ trust. Loop runs only over converted personas (small set);
each step is a CSR slice + fancy index.
"""

from __future__ import annotations
 
from collections.abc import Sequence
 
import numpy as np
 
from society.graph.model import SocialGraph
from society.report.frame import Frame
from society.report.schemas import Influencer, SpreadStat
from society.schemas import Persona
 
_TOP_K = 10
_INFLUENCE_TRIGGER = 1


def spread_stats(frame: Frame, graph: SocialGraph, personas: Sequence[Persona]) -> SpreadStat:
    n = frame.n
    credit = np.zeros(n, np.float64)
    converted = np.flatnonzero((frame.first_adopt > 0) & (frame.adopt_trigger == _INFLUENCE_TRIGGER))
 
    for i in converted.tolist():
        r = int(frame.first_adopt[i])
        nbrs, w = graph.listens_to(i)
        if nbrs.size == 0:
            continue
        m = frame.share[r - 1, nbrs]
        if m.any():
            tw = w[m].astype(np.float64)
            np.add.at(credit, nbrs[m], tw / tw.sum())
 
    organic = int((frame.first_adopt == 0).sum())
    influenced = int(converted.size)
    adopters_ever = organic + int(((frame.first_adopt > 0) & (frame.adopt_trigger != _INFLUENCE_TRIGGER)).sum()) + influenced
    in_deg = graph.in_degrees()
    top = np.argsort(-credit, kind="stable")[:_TOP_K]
    top = top[credit[top] > 0]
 
    return SpreadStat(
        organic_adopters=organic,
        influenced_adopters=influenced,
        influenced_share=round(influenced / adopters_ever, 4) if adopters_ever else 0.0,
        channel_touched_share=round(float(frame.adopt_channel[converted].mean()), 4) if influenced else 0.0,
        top_influencers=[
            Influencer(index=int(j), persona_id=personas[j].id,
                       name=personas[j].profile.name if personas[j].profile else personas[j].id,
                       influence=personas[j].traits.influence, in_degree=int(in_deg[j]),
                       conversions_credited=round(float(credit[j]), 3))
            for j in top.tolist()
        ],
    )
