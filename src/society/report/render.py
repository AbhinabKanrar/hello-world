"""Report → Markdown. Pure string building; no I/O."""
 
from __future__ import annotations
 
from collections.abc import Iterable, Sequence
 
from society.report.schemas import Report
 
_PCT = "{:.1%}".format


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return f"| {' | '.join(headers)} |\n|{'---|' * len(headers)}\n{body}"


def to_markdown(r: Report) -> str:  # noqa: PLR0915 - a template is naturally linear
    h, c, p = r.headline, r.confidence, r.price
    out: list[str] = [f"# {r.scenario}", ""]
    out += [f"**Verdict: {h.verdict.upper()}** — final adoption **{_PCT(h.final_adoption)}** "
            f"(95% CI {_PCT(c.adoption_ci_low)}–{_PCT(c.adoption_ci_high)}, n={c.n}), "
            f"peak {_PCT(h.peak_adoption)} in round {h.peak_round}, trend *{h.trend}*.", ""]
    if r.narrative:
        out += ["## Summary", r.narrative.summary, "", "### Recommendations"]
        out += [f"{i}. {rec}" for i, rec in enumerate(r.narrative.recommendations, 1)]
        out.append("")
 
    out += ["## Adoption over time", _table(
        ["Round", "Adoption", "Mean interest", "Sharers", "Event"],
        ((pt.round, _PCT(pt.adoption), f"{pt.mean_interest:.2f}", pt.sharers, pt.event or "") for pt in r.curve)), ""]
 
    strong = [s for s in r.segments if not s.low_n]
    out += ["## Segments (sorted by lift)", _table(
        ["Dimension", "Bucket", "n", "Adoption", "Mean intent", "Lift"],
        ((s.dimension, s.bucket, s.n, _PCT(s.adoption), f"{s.mean_intent:.2f}", f"{s.lift:.2f}×") for s in strong)), ""]
    if low := [s for s in r.segments if s.low_n]:
        out += [f"_{len(low)} small segments (n<10) omitted._", ""]
 
    out += ["## Pricing",
            f"- List price {p.list_price:g}: **{_PCT(p.list_price_share)}** would pay; {_PCT(p.share_unwilling)} would pay nothing.",
            f"- Median willingness to pay: {p.median_max_price:g}."]
    if p.revenue_max_price is not None:
        out.append(f"- Revenue-maximising price: **{p.revenue_max_price:g}** ({_PCT(p.revenue_max_share or 0)} willing).")
    if p.suggested_tiers:
        out.append(f"- Suggested tiers: {', '.join(f'{t:g}' for t in p.suggested_tiers)}.")
    out.append("")
 
    out += ["## Top objections", _table(
        ["Theme", "Count", "Share", "Loudest segments"],
        ((o.label, o.count, _PCT(o.share), ", ".join(o.top_segments)) for o in r.objections)), ""]
 
    s = r.spread
    out += ["## How it spread",
            f"- Organic adopters (round 0): {s.organic_adopters}; influenced adopters: {s.influenced_adopters} "
            f"({_PCT(s.influenced_share)} of all adopters); {_PCT(s.channel_touched_share)} of conversions touched a channel."]
    if s.top_influencers:
        out += ["", _table(["Influencer", "Influence", "In-degree", "Conversions credited"],
                           ((i.name, f"{i.influence:.2f}", i.in_degree, f"{i.conversions_credited:.1f}") for i in s.top_influencers))]
    out.append("")
 
    if r.events:
        out += ["## Event impact", _table(
            ["Round", "Event", "Δ adoption", "Δ interest", "Baseline drift", "Notable"],
            ((e.round, f"{e.kind}: {e.detail}", f"{e.delta_adoption:+.1%}", f"{e.delta_interest:+.2f}",
              f"{e.baseline_drift:+.1%}", "✅" if e.notable else "") for e in r.events)), ""]
 
    if r.voices:
        out += ["## Voices"]
        out += [f"> **{q.name}** ({q.segment}, intent {q.purchase_intent}/5): {q.text}" for q in r.voices]
        out.append("")
 
    out += ["---", f"_n={c.n}, rounds={c.rounds}, generated {r.generated_at:%Y-%m-%d %H:%M} UTC"
            + (f", cache hit ratio {c.cache_hit_ratio:.0%}" if c.cache_hit_ratio is not None else "") + "._"]
    return "\n".join(out)
