"""Struct-of-arrays population state. O(1) updates, cheap checkpointing."""
 
from __future__ import annotations
 
import numpy as np
from numpy.typing import NDArray
 
from society.sim.schemas import Checkpoint, Reaction, SimEvent


class PopulationState:
    __slots__ = (
        "interest", "max_price", "n", "purchase_intent", "share_message",
        "stance", "top_objection", "updated_round", "would_share",
    )
 
    def __init__(self, n: int) -> None:
        self.n = n
        self.interest = np.ones(n, dtype=np.int8)
        self.purchase_intent = np.ones(n, dtype=np.int8)
        self.max_price = np.zeros(n, dtype=np.float32)
        self.would_share = np.zeros(n, dtype=np.bool_)
        self.updated_round = np.full(n, -1, dtype=np.int32)
        self.top_objection: list[str] = [""] * n
        self.share_message: list[str] = [""] * n
        self.stance: list[str] = ["No opinion yet."] * n
 
    # ------------------------------------------------------------- updates
    def apply(self, i: int, r: Reaction, rnd: int) -> None:
        self.interest[i] = r.interest
        self.purchase_intent[i] = r.purchase_intent
        self.max_price[i] = r.max_price
        self.would_share[i] = r.would_share and bool(r.share_message.strip())
        self.updated_round[i] = rnd
        self.top_objection[i] = r.top_objection
        self.share_message[i] = r.share_message if self.would_share[i] else ""
        self.stance[i] = r.stance
 
    def decay(self, rnd: int, *, every: int, exclude: NDArray[np.bool_]) -> NDArray[np.int64]:
        """Novelty fades: idle personas lose one interest point every `every` rounds."""
        idle = (rnd - self.updated_round) >= every
        target = idle & ~exclude & (self.interest > 1) & (self.updated_round >= 0)
        idx = np.flatnonzero(target)
        if idx.size:
            self.interest[idx] -= 1
            # Intent can't exceed interest; stale sharers stop sharing.
            self.purchase_intent[idx] = np.minimum(self.purchase_intent[idx], self.interest[idx])
            self.would_share[idx] = False
            self.updated_round[idx] = rnd
        return idx
 
    def spoke_in(self, rnd: int) -> NDArray[np.bool_]:
        return (self.updated_round == rnd) & self.would_share
 
    # ------------------------------------------------------------- metrics
    def adoption(self) -> float:
        return float(np.mean(self.purchase_intent >= 4)) if self.n else 0.0
 
    def mean_interest(self) -> float:
        return float(self.interest.mean()) if self.n else 0.0
 
    # --------------------------------------------------------------- rows
    def row(self, i: int, rnd: int, trigger: str, persona_id: str, *, reasoning: str = "",
            peer: int = 0, channel: int = 0, events: int = 0) -> SimEvent:
        return SimEvent(
            round=rnd, index=i, persona_id=persona_id, trigger=trigger,  # type: ignore[arg-type]
            interest=int(self.interest[i]), purchase_intent=int(self.purchase_intent[i]),
            max_price=float(self.max_price[i]), would_share=bool(self.would_share[i]),
            top_objection=self.top_objection[i], share_message=self.share_message[i],
            stance=self.stance[i], reasoning=reasoning,
            peer_msgs=peer, channel_msgs=channel, events=events,
        )
 
    # --------------------------------------------------------- checkpoint
    def to_checkpoint(self, *, scenario_hash: str, seed: int, completed_round: int) -> Checkpoint:
        return Checkpoint(
            scenario_hash=scenario_hash, seed=seed, completed_round=completed_round,
            interest=self.interest.tolist(), purchase_intent=self.purchase_intent.tolist(),
            max_price=self.max_price.tolist(), would_share=self.would_share.tolist(),
            updated_round=self.updated_round.tolist(), top_objection=self.top_objection,
            share_message=self.share_message, stance=self.stance,
        )
 
    @classmethod
    def from_checkpoint(cls, c: Checkpoint) -> PopulationState:
        s = cls(len(c.interest))
        s.interest[:] = c.interest
        s.purchase_intent[:] = c.purchase_intent
        s.max_price[:] = c.max_price
        s.would_share[:] = c.would_share
        s.updated_round[:] = c.updated_round
        s.top_objection, s.share_message, s.stance = list(c.top_objection), list(c.share_message), list(c.stance)
        return s
