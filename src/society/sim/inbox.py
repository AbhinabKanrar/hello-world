"""Message routing over the CSR graph. Produces, per round, the *dirty set* — personas whose
inputs changed — and their inboxes. Everyone else is untouched (no LLM call).

Complexity per round: O(edges) NumPy for peer routing; O(top_k × channels) for broadcasts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from society.graph.model import SocialGraph
from society.sim.schemas import ScenarioEvent


@dataclass(frozen=True, slots=True)
class PeerMsg:
    sender: int
    trust: float
    text: str


@dataclass(frozen=True, slots=True)
class ChannelMsg:
    channel: str
    sender: int
    text: str


@dataclass(slots=True)
class Inbox:
    peers: list[PeerMsg] = field(default_factory=list)
    channel: list[ChannelMsg] = field(default_factory=list)
    events: tuple[ScenarioEvent, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.peers or self.channel or self.events)


class InboxRouter:
    __slots__ = ("_g", "_influence", "_max_channel", "_max_peer", "_members", "_slug", "_top_k")

    def __init__(
        self,
        graph: SocialGraph,
        influence: NDArray[np.float32],
        *,
        max_peer: int,
        max_channel: int,
        broadcast_top_k: int,
    ) -> None:
        self._g = graph
        self._influence = influence
        self._max_peer = max_peer
        self._max_channel = max_channel
        self._top_k = broadcast_top_k
        self._members = graph.channel_members()
        self._slug = {cid: cid.split(":", 1)[1] for cid in self._members}

    def route(
        self,
        *,
        sharers: NDArray[np.bool_],
        messages: Sequence[str],
        events: tuple[ScenarioEvent, ...],
        engaged: NDArray[np.bool_] | None = None,
    ) -> dict[int, Inbox]:
        """`sharers[j]` = j produced a new share_message last round."""
        g = self._g
        inboxes: dict[int, Inbox] = {}

        # ---- peers: edge (i → j) delivers j's message to i when j shared.
        if sharers.any() and g.edges:
            hit = sharers[g.indices]
            dirty_rows = np.unique(np.searchsorted(g.indptr, np.flatnonzero(hit), side="right") - 1)
            for i in dirty_rows.tolist():
                nbrs, w = g.listens_to(i)
                m = sharers[nbrs]
                nb, tw = nbrs[m], w[m]
                if nb.size > self._max_peer:
                    keep = np.argpartition(-tw, self._max_peer - 1)[: self._max_peer]
                    nb, tw = nb[keep], tw[keep]
                order = np.argsort(-tw, kind="stable")
                inboxes[i] = Inbox(
                    peers=[
                        PeerMsg(int(j), float(t), messages[j])
                        for j, t in zip(nb[order], tw[order], strict=True)
                    ]
                )

        # ---- channels: top-k sharers by influence broadcast to every channel they belong to.
        if self._top_k and self._max_channel and sharers.any():
            cand = np.flatnonzero(sharers)
            top = cand[np.argsort(-self._influence[cand], kind="stable")[: self._top_k]]
            posts: dict[str, list[int]] = {}
            for j in top.tolist():
                for cid in g.memberships[j]:
                    posts.setdefault(cid, []).append(j)
            # for cid, senders in posts.items():
            #     for i in self._members[cid].tolist():
            #         box = inboxes.setdefault(i, Inbox())
            #         for j in senders:
            #             if j != i and len(box.channel) < self._max_channel:
            #                 box.channel.append(ChannelMsg(cid.split(":", 1)[1], j, messages[j]))
            if posts:
                names = [self._slug[cid] for cid in posts]
                rcv_p, snd_p, ch_p = [], [], []

                for c, (cid, senders) in enumerate(posts.items()):
                    mem, snd = self._members[cid], np.asarray(senders, np.int64)
                    rcv_p.append(np.repeat(mem, snd.size))
                    snd_p.append(np.tile(snd, mem.size))
                    ch_p.append(np.full(mem.size * snd.size, c, np.int64))

                rcv, snd, ch = (np.concatenate(p) for p in (rcv_p, snd_p, ch_p))
                keep = rcv != snd  # never deliver your own post to yourself
                order = np.argsort(rcv[keep], kind="stable")  # preserves channel→sender order
                rcv, snd, ch = rcv[keep][order], snd[keep][order], ch[keep][order]
                rank = np.arange(rcv.size) - np.searchsorted(rcv, rcv, side="left")
                cap = rank < self._max_channel
                for i, j, c in zip(
                    rcv[cap].tolist(), snd[cap].tolist(), ch[cap].tolist(), strict=True
                ):
                    inboxes.setdefault(i, Inbox()).channel.append(
                        ChannelMsg(names[c], j, messages[j])
                    )

        # ---- events reach everyone.
        if events:
            # for i in range(g.n):
            #     inboxes.setdefault(i, Inbox()).events = events

            targets = np.arange(g.n) if engaged is None else np.flatnonzero(engaged)

            for i in targets.tolist():
                inboxes.setdefault(i, Inbox()).events = events
            for box in inboxes.values():  # peers/channel recipients also hear the news
                box.events = events

        return inboxes
