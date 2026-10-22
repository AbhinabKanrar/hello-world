"""Layer 4 orchestrator. Deterministic given (sim outputs, seed); LLM pieces are optional."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from society.graph.model import SocialGraph
from society.llm.base import ChatClient
from society.report import metrics
from society.report.frame import ADOPT_THRESHOLD, Frame
from society.report.html import to_html
from society.report.narrative import write_narrative
from society.report.objections import objection_themes
from society.report.render import to_markdown
from society.report.schemas import Quote, Report, SegmentStat
from society.report.spread import spread_stats
from society.schemas import Persona
from society.sim.schemas import ScenarioSpec


_log = logging.getLogger(__name__)
_VOICE_SEGMENTS = 3


class ReportBuilder:
    __slots__ = ("_client", "_narrative", "_seed")

    def __init__(self, client: ChatClient | None, *, seed: int = 0, narrative: bool = True) -> None:
        self._client = client
        self._seed = seed
        self._narrative = narrative and client is not None

    async def build(
        self,
        *,
        personas: Sequence[Persona],
        graph: SocialGraph,
        sim_dir: Path,
        scenario: ScenarioSpec,
    ) -> Report:
        if graph.n != len(personas):
            raise ValueError("report graph size does not match the population")
        if any(persona.index != i for i, persona in enumerate(personas)):
            raise ValueError("personas must be ordered by contiguous index")

        frame = Frame.load(
            sim_dir,
            expected_n=len(personas),
            expected_scenario_hash=scenario.content_hash(),
            expected_ids=[persona.id for persona in personas],
        )
        curve = metrics.adoption_curve(frame, scenario)
        head = metrics.headline(curve)
        segments = metrics.segment_stats(frame, personas)
        price = metrics.price_curve(frame, scenario.price.amount)
        events = metrics.event_impacts(curve, scenario)
        conf = metrics.confidence(frame, seed=self._seed)
        spread = spread_stats(frame, graph, personas)
        styles = [p.traits.decision_style.value for p in personas]
        objections = await objection_themes(frame.objection, styles, self._client)
        voices = _voices(frame, personas, segments)
        narrative = None
        if self._narrative and self._client is not None:
            narrative = await write_narrative(
                self._client,
                name=scenario.name,
                headline=head,
                segments=segments,
                price=price,
                objections=objections,
                events=events,
                seed=self._seed,
            )
        _log.info(
            "report_built", extra={"verdict": head.verdict, "final_adoption": head.final_adoption}
        )
        return Report(
            scenario=scenario.name,
            scenario_hash=scenario.content_hash(),
            headline=head,
            curve=curve,
            segments=segments,
            price=price,
            objections=objections,
            spread=spread,
            events=events,
            voices=voices,
            confidence=conf,
            narrative=narrative,
        )

    @staticmethod
    def write(report: Report, out_dir: Path) -> tuple[Path, Path]:
        # Render first so a rendering failure does not overwrite existing outputs.
        html_content = to_html(report)
        json_content = report.model_dump_json(indent=2)
        markdown_content = to_markdown(report)

        out_dir.mkdir(parents=True, exist_ok=True)
        js = out_dir / "report.json"
        md = out_dir / "report.md"
        html = out_dir / "report.html"

        js.write_text(json_content, encoding="utf-8")
        md.write_text(markdown_content, encoding="utf-8")
        html.write_text(html_content, encoding="utf-8")
        return js, md


def _voices(
    frame: Frame, personas: Sequence[Persona], segments: Sequence[SegmentStat]
) -> list[Quote]:
    """One adopter quote from each top-lift segment and one rejecter from each bottom segment."""
    strong = [s for s in segments if not s.low_n]
    picks = [(s, True) for s in strong[:_VOICE_SEGMENTS]] + [
        (s, False) for s in strong[-_VOICE_SEGMENTS:]
    ]
    label_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {
        dim: (idx, labels) for dim, idx, labels in metrics.dimension_labels(personas)
    }
    intent = frame.intent[-1]
    seen: set[int] = set()
    out: list[Quote] = []
    for seg, adopter in picks:
        idx, labels = label_cache[seg.dimension]
        members = np.unique(idx[labels == seg.bucket])
        adoption_mask = intent[members] >= ADOPT_THRESHOLD
        members = members[adoption_mask if adopter else ~adoption_mask]
        members = members[[bool(frame.reasoning[m]) and m not in seen for m in members]]
        if members.size == 0:
            continue
        i = int(members[intent[members].argmax() if adopter else intent[members].argmin()])
        seen.add(i)
        p = personas[i]
        out.append(
            Quote(
                persona_id=p.id,
                name=p.profile.name if p.profile else p.id,
                segment=f"{seg.dimension}={seg.bucket}",
                purchase_intent=int(intent[i]),
                text=frame.reasoning[i],
            )
        )
    return out
