"""Prompt rendering. Pure functions; persona cards are rendered once and reused every round."""

from __future__ import annotations

import json
from collections.abc import Sequence

from society.schemas import Persona, Segment
from society.sim.inbox import Inbox
from society.sim.schemas import ScenarioSpec

SYSTEM = (
    "You are role-playing ONE specific consumer described below. Stay strictly in character: "
    "their budget, skepticism, habits and social circle drive every answer. Be realistic — most "
    "people are indifferent to most products. Never break character or mention being an AI. "
    "Return JSON only, matching the schema exactly."
)

_LEVEL = {1: "very low", 2: "low", 3: "moderate", 4: "high", 5: "very high"}


def persona_card(p: Persona) -> str:
    t = p.traits
    lines = [
        f"Facts: {json.dumps(p.attributes, ensure_ascii=False, separators=(',', ':'))}",
        f"Openness to new products: {_LEVEL[t.openness]} | Price sensitivity: {_LEVEL[t.price_sensitivity]} "
        f"| Skepticism of marketing: {_LEVEL[t.skepticism]} | Decision style: {t.decision_style.value}",
    ]
    if t.segment is Segment.NON_BUYER:
        lines.append(
            "Note: this person currently has no intention of spending money on this problem."
        )
    if p.profile:
        lines += [
            f"Name: {p.profile.name} ({p.profile.city})",
            f"Bio: {p.profile.bio}",
            f"How they handle it today: {p.profile.current_solution}",
            f"What would make them switch: {p.profile.switch_trigger}",
        ]
    return "\n".join(lines)


def scenario_block(s: ScenarioSpec, price_override: str | None = None) -> str:
    return f'Product: {s.product}\nPitch: "{s.pitch}"\nPrice: {price_override or s.price.render()}'


def exposure_prompt(card: str, scenario: str) -> str:
    return (
        f"=== WHO YOU ARE ===\n{card}\n\n"
        f"=== YOU JUST SAW THIS FOR THE FIRST TIME ===\n{scenario}\n\n"
        "React honestly as this person. Give: interest (1-5), purchase_intent (1-5), max_price "
        "(the most you'd pay per period, 0 if never), top_objection, whether you'd mention it to "
        "others (would_share) and exactly what you'd say (share_message, empty if not sharing), a "
        "one-line stance, and brief reasoning."
    )


def _trust_word(w: float) -> str:
    return "trusted" if w >= 0.7 else "acquaintance" if w >= 0.4 else "barely known"


def update_prompt(
    card: str, scenario: str, prior_stance: str, inbox: Inbox, names: Sequence[str]
) -> str:
    parts = [
        f"=== WHO YOU ARE ===\n{card}",
        f"=== THE PRODUCT ===\n{scenario}",
        f"=== YOUR VIEW SO FAR ===\n{prior_stance}",
    ]
    heard: list[str] = []
    heard += [f'- {names[m.sender]} ({_trust_word(m.trust)}): "{m.text}"' for m in inbox.peers]
    heard += [f'- [{m.channel}] {names[m.sender]}: "{m.text}"' for m in inbox.channel]
    heard += [f"- {e.kind.value.upper()}: {e.detail}" for e in inbox.events]
    parts.append("=== SINCE THEN YOU HEARD ===\n" + "\n".join(heard))
    parts.append(
        "Update your view as this person would — people rarely swing wildly, but trusted friends, "
        "bad news and price changes matter. Return the full JSON again (interest, purchase_intent, "
        "max_price, top_objection, would_share, share_message, stance, reasoning)."
    )
    return "\n\n".join(parts)
