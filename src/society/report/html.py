"""Self-contained aggregate dashboard. No network, external assets, or LLM calls."""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape

from society.report.schemas import Report

_SEGMENT_LIMIT = 500
_MAX_DATA_BYTES = 2_000_000

_CSS = r"""
:root {
  color-scheme: light;
  --ink: #17243b;
  --muted: #59677c;
  --accent: #315bd6;
  --border: #dce3ed;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: #f3f6fb; color: var(--ink);
  font: 15px/1.6 system-ui, -apple-system, sans-serif;
}
main { max-width: 1240px; margin: auto; padding: 32px 20px 60px; }
h1 { font-size: clamp(26px, 4vw, 40px); margin: 8px 0; line-height: 1.2; }
h2 { font-size: 22px; margin: 0 0 12px; }
h3 { font-size: 16px; margin: 0 0 12px; }
p { margin: 8px 0 16px; }
a { color: var(--accent); }
header { margin-bottom: 22px; }
.eyebrow { text-transform: uppercase; letter-spacing: .14em; font-weight: 700; }
.muted, small, .meta { color: var(--muted); }
.meta { font-size: 13px; overflow-wrap: anywhere; }
nav, .controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
nav { padding: 14px 0; }
section { margin: 24px 0; scroll-margin-top: 20px; }
.card, section {
  background: white; border: 1px solid var(--border);
  border-radius: 14px; padding: 22px;
}
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.kpi-value { display: block; font-size: 30px; font-weight: 750; }
.notice {
  border-left: 4px solid #bb7900; background: #fff8e8;
  padding: 14px 18px; border-radius: 6px; margin: 16px 0;
}
.chart { min-width: 0; }
.chart svg { display: block; width: 100%; height: auto; }
.chart text { font: 12px system-ui, sans-serif; fill: var(--muted); }
.gridline { stroke: #e5eaf2; stroke-width: 1; }
.series { fill: none; stroke: var(--accent); stroke-width: 3; }
.point { fill: var(--accent); stroke: white; stroke-width: 2; }
.event-line { stroke: #bd7800; stroke-dasharray: 4 4; }
.controls { margin-bottom: 16px; }
label { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
input, select, button {
  font: inherit; padding: 8px 10px; border: 1px solid #b8c5d8;
  border-radius: 7px; background: white; color: var(--ink);
}
input[type="search"] { max-width: 100%; }
button { cursor: pointer; }
button:disabled { cursor: default; opacity: .45; }
:focus-visible { outline: 3px solid #b65c00; outline-offset: 3px; }
.table-wrap { overflow-x: auto; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
caption { text-align: left; font-weight: 650; margin-bottom: 8px; }
th, td {
  text-align: left; vertical-align: top; padding: 10px;
  border-bottom: 1px solid var(--border); overflow-wrap: anywhere;
}
th { background: #f4f7fc; white-space: nowrap; }
td { max-width: 440px; }
.pager { display: flex; gap: 12px; align-items: center; margin-top: 14px; }
.bar-row { display: grid; grid-template-columns: 2fr 3fr 1fr; gap: 12px; margin: 9px 0; }
.bar-row span { overflow-wrap: anywhere; }
meter { width: 100%; height: 24px; }
details { border-top: 1px solid var(--border); padding: 12px 0; }
summary { cursor: pointer; font-weight: 650; }
blockquote {
  margin: 12px 0; padding: 8px 16px; border-left: 3px solid #c9d5eb;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.prose { white-space: pre-wrap; overflow-wrap: anywhere; }
footer { color: var(--muted); font-size: 13px; margin-top: 26px; }
@media (max-width: 800px) {
  .grid { grid-template-columns: 1fr; }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  section, .card { padding: 16px; }
}
@media print {
  body { background: white; font-size: 11px; }
  main { max-width: none; padding: 0; }
  nav, .controls, .pager, button { display: none; }
  section, .card { border-radius: 0; break-inside: avoid; }
  .grid { display: block; }
  .table-wrap { overflow: visible; }
}
"""

_JS = r"""
"use strict";
(() => {
  const payload = JSON.parse(document.getElementById("report-data").textContent);
  const r = payload.report;
  const pct = x => `${(x * 100).toFixed(1)}%`;
  const num = x => Number.isFinite(x)
    ? x.toLocaleString(undefined, {maximumFractionDigits: 2}) : "—";
  const pp = x => `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)} pp`;

  function node(tag, text, className) {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (className) n.className = className;
    return n;
  }

  function section(id, title, description) {
    const s = node("section");
    s.id = id;
    s.append(node("h2", title));
    if (description) s.append(node("p", description, "muted"));
    document.getElementById("dashboard").append(s);
    return s;
  }

  function table(parent, title, headers, rows) {
    const wrap = node("div", undefined, "table-wrap");
    const t = node("table");
    t.append(node("caption", title));
    const head = node("thead");
    const hr = node("tr");
    for (const label of headers) {
      const th = node("th", label);
      th.scope = "col";
      hr.append(th);
    }
    head.append(hr);
    const body = node("tbody");
    for (const row of rows) {
      const tr = node("tr");
      for (const value of row) tr.append(node("td", value));
      body.append(tr);
    }
    if (!rows.length) {
      const td = node("td", "No data available.");
      td.colSpan = headers.length;
      const tr = node("tr");
      tr.append(td);
      body.append(tr);
    }
    t.append(head, body);
    wrap.append(t);
    parent.append(wrap);
  }

  function svgNode(tag, attributes = {}, text) {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attributes)) {
      n.setAttribute(key, String(value));
    }
    if (text !== undefined) n.textContent = String(text);
    return n;
  }

  function lineChart(parent, title, points, format, ceiling, events = []) {
    const card = node("div", undefined, "card chart");
    card.append(node("h3", title));
    const valid = points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
    if (!valid.length) {
      card.append(node("p", "No data available.", "muted"));
      parent.append(card);
      return;
    }

    const svg = svgNode("svg", {
      viewBox: "0 0 560 250", role: "img", "aria-label": title
    });
    svg.append(svgNode("title", {}, title));
    const xs = valid.map(p => p.x);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const maxY = Math.max(ceiling || 0, ...valid.map(p => p.y), 0.001);
    const x = v => maxX === minX ? 300 : 65 + (v - minX) / (maxX - minX) * 460;
    const y = v => 205 - v / maxY * 175;

    for (let i = 0; i <= 4; i++) {
      const value = maxY * i / 4;
      svg.append(svgNode("line", {
        x1: 65, x2: 525, y1: y(value), y2: y(value), class: "gridline"
      }));
      svg.append(svgNode("text", {
        x: 57, y: y(value) + 4, "text-anchor": "end"
      }, format(value)));
    }

    for (const event of events) {
      if (event.round < minX || event.round > maxX) continue;
      const marker = svgNode("line", {
        x1: x(event.round), x2: x(event.round), y1: 25, y2: 205,
        class: "event-line"
      });
      marker.append(svgNode("title", {}, `Round ${event.round}: ${event.detail}`));
      svg.append(marker);
    }

    svg.append(svgNode("polyline", {
      points: valid.map(p => `${x(p.x)},${y(p.y)}`).join(" "), class: "series"
    }));
    for (const p of valid) {
      const description = `${p.label}: ${format(p.y)}`;
      const dot = svgNode("circle", {
        cx: x(p.x), cy: y(p.y), r: 4, class: "point",
        tabindex: 0, "aria-label": description
      });
      dot.append(svgNode("title", {}, description));
      svg.append(dot);
    }
    const ticks = minX === maxX ? [minX] : [minX, (minX + maxX) / 2, maxX];
    for (const tick of ticks) {
      svg.append(svgNode("text", {
        x: x(tick), y: 232, "text-anchor": "middle"
      }, num(tick)));
    }
    card.append(svg);
    parent.append(card);
  }

  function bars(parent, rows) {
    if (!rows.length) parent.append(node("p", "No matching data.", "muted"));
    for (const [label, value] of rows) {
      const row = node("div", undefined, "bar-row");
      const meter = node("meter");
      meter.min = 0;
      meter.max = 1;
      meter.value = value;
      meter.setAttribute("aria-label", `${label}: ${pct(value)}`);
      row.append(node("span", label), meter, node("strong", pct(value)));
      parent.append(row);
    }
  }

  const summary = section("overview", "Decision overview");
  summary.append(node("p",
    "Synthetic responses are hypotheses to validate, not measured demand.", "notice"));
  const cards = node("div", undefined, "grid kpis");
  const metrics = [
    ["Final high purchase intent", pct(r.headline.final_adoption)],
    ["Peak high purchase intent", pct(r.headline.peak_adoption)],
    ["Synthetic personas", num(r.confidence.n)],
    ["Post-exposure rounds", num(r.confidence.rounds)]
  ];
  for (const [label, value] of metrics) {
    const card = node("div", undefined, "card");
    card.append(node("span", label, "muted"), node("strong", value, "kpi-value"));
    cards.append(card);
  }
  summary.append(cards);
  summary.append(node("p",
    `Heuristic band: ${r.headline.verdict}. Trend: ${r.headline.trend}. ` +
    `High purchase intent means a score of at least 4/5—not a completed purchase.`));
  if (r.confidence.n < 200) {
    summary.append(node("p",
      "Small exploratory run. Increasing synthetic population size does not by itself " +
      "establish real-world accuracy.", "notice"));
  }
  if (r.narrative) {
    summary.append(node("h3", "Generated interpretation"));
    summary.append(node("p", r.narrative.summary, "prose"));
    const list = node("ol");
    for (const rec of r.narrative.recommendations) list.append(node("li", rec));
    summary.append(list);
  }

  const response = section("response", "Response over time",
    "Round 0 is initial exposure. Amber dashed lines indicate scenario events. " +
    "Interest and sharing reflect the saved simulation state.");
  const responseGrid = node("div", undefined, "grid");
  response.append(responseGrid);
  const roundPoints = field => r.curve.map(p => ({
    x: p.round, y: p[field], label: `Round ${p.round}`
  }));
  lineChart(responseGrid, "High purchase intent · fraction",
    roundPoints("adoption"), pct, 1, r.events);
  lineChart(responseGrid, "Mean interest · score out of 5",
    roundPoints("mean_interest"), num, 5, r.events);
  lineChart(responseGrid, "Sharing state · personas",
    roundPoints("sharers"), num, r.confidence.n, r.events);
  const responseDetails = node("details");
  responseDetails.append(node("summary", "View round values"));
  table(responseDetails, "Round metrics",
    ["Round", "High intent", "Mean interest", "Sharing", "Event"],
    r.curve.map(p => [
      p.round, pct(p.adoption), num(p.mean_interest), p.sharers, p.event || "—"
    ]));
  response.append(responseDetails);

  const segments = section("segments", "Audience segments",
    "Filter and compare aggregate groups. Membership may overlap; counts must not be summed.");
  segments.append(node("p",
    `Embedded ${r.segments.length} of ${payload.segment_total} segment summaries. ` +
    "Filtering searches these summaries only. Complete segment data remains in report.json.",
    "meta"));
  const controls = node("div", undefined, "controls");
  const search = node("input");
  search.type = "search";
  search.placeholder = "Search segment summaries";
  search.setAttribute("aria-label", "Search segment summaries");
  const dimension = node("select");
  dimension.setAttribute("aria-label", "Segment dimension");
  const all = node("option", "All dimensions");
  all.value = "";
  dimension.append(all);
  for (const value of [...new Set(r.segments.map(s => s.dimension))].sort()) {
    const option = node("option", value);
    option.value = value;
    dimension.append(option);
  }
  const sort = node("select");
  sort.setAttribute("aria-label", "Sort segment summaries");
  for (const [value, label] of [
    ["adoption", "Highest purchase intent"], ["n", "Largest groups"],
    ["lift", "Highest lift"]
  ]) {
    const option = node("option", label);
    option.value = value;
    sort.append(option);
  }
  const low = node("input");
  low.type = "checkbox";
  const lowLabel = node("label");
  lowLabel.append(low, node("span", "Include groups smaller than 10"));
  controls.append(search, dimension, sort, lowLabel);
  segments.append(controls);
  const segmentBars = node("div");
  const segmentTable = node("div");
  const pager = node("div", undefined, "pager");
  const previous = node("button", "Previous");
  const next = node("button", "Next");
  previous.type = next.type = "button";
  const status = node("span");
  status.setAttribute("role", "status");
  pager.append(previous, status, next);
  segments.append(segmentBars, segmentTable, pager);
  segments.append(node("p",
    "Print output contains the current table page. Use report.json or report.md " +
    "for the complete segment list.", "meta"));
  let page = 0;
  function updateSegments() {
    const query = search.value.trim().toLowerCase();
    const matches = r.segments.filter(s =>
      (low.checked || !s.low_n) &&
      (!dimension.value || s.dimension === dimension.value) &&
      `${s.dimension} ${s.bucket}`.toLowerCase().includes(query)
    ).sort((a, b) => b[sort.value] - a[sort.value] ||
      a.dimension.localeCompare(b.dimension) || a.bucket.localeCompare(b.bucket));
    const pages = Math.max(1, Math.ceil(matches.length / 20));
    page = Math.min(page, pages - 1);
    segmentBars.replaceChildren(node("h3",
      "Purchase-intent share · first 10 groups in the selected order"));
    bars(segmentBars, matches.slice(0, 10).map(s => [
      `${s.dimension}: ${s.bucket} (n=${s.n})`, s.adoption
    ]));
    segmentTable.replaceChildren();
    table(segmentTable, "Segment comparison",
      ["Dimension", "Group", "n", "High intent", "Mean intent", "Lift", "Small group"],
      matches.slice(page * 20, page * 20 + 20).map(s => [
        s.dimension, s.bucket, s.n, pct(s.adoption), num(s.mean_intent),
        r.headline.final_adoption > 0 ? `${num(s.lift)}×` : "Undefined",
        s.low_n ? "Yes" : "No"
      ]));
    status.textContent = `${matches.length} groups · Page ${page + 1} of ${pages}`;
    previous.disabled = page === 0;
    next.disabled = page + 1 === pages;
  }
  search.addEventListener("input", () => { page = 0; updateSegments(); });
  for (const control of [dimension, sort, low]) {
    control.addEventListener("change", () => { page = 0; updateSegments(); });
  }
  previous.addEventListener("click", () => { page--; updateSegments(); });
  next.addEventListener("click", () => { page++; updateSegments(); });
  updateSegments();

  const pricing = section("pricing", "Stated willingness to pay",
    "Prices use the scenario's units; currency and billing period are not stored in " +
    "this report schema. This is not measured price elasticity or forecast revenue.");
  pricing.append(node("p",
    `Original scenario list price: ${num(r.price.list_price)}. ` +
    `Stated acceptance: ${pct(r.price.list_price_share)}. ` +
    `Would pay nothing: ${pct(r.price.share_unwilling)}.`));
  pricing.append(node("p",
    `Median among positive stated prices: ${num(r.price.median_max_price)}. ` +
    `Best price on the sampled grid: ${r.price.revenue_max_price === null
      ? "unavailable" : num(r.price.revenue_max_price)}.`));
  const priceGrid = node("div", undefined, "grid");
  pricing.append(priceGrid);
  const pricePoints = field => r.price.points.map(p => ({
    x: p.price, y: p[field], label: `Price ${num(p.price)}`
  }));
  lineChart(priceGrid, "Stated willingness · fraction vs price",
    pricePoints("share_willing"), pct, 1);
  lineChart(priceGrid, "Revenue index · price × willing fraction",
    pricePoints("revenue_index"), num, 0);
  const priceDetails = node("details");
  priceDetails.append(node("summary", "View price-grid values"));
  table(priceDetails, "Pricing grid", ["Price", "Willing share", "Revenue index"],
    r.price.points.map(p => [num(p.price), pct(p.share_willing), num(p.revenue_index)]));
  pricing.append(priceDetails);

  const objections = section("objections", "Objections",
    "Theme counts describe synthetic responses, not verified customer feedback.");
  bars(objections, r.objections.map(o => [o.label, o.share]));
  for (const o of r.objections) {
    const details = node("details");
    details.append(node("summary", `${o.label} · ${o.count} responses`));
    details.append(node("p", `Associated segments: ${o.top_segments.join(", ") || "—"}`));
    for (const quote of o.quotes) details.append(node("blockquote", quote));
    objections.append(details);
  }

  const social = section("social", "Social dynamics",
    "Attribution is a simulation heuristic, not causal evidence. " +
    "These counts refer to first adoption during the run, not necessarily final adopters.");
  social.append(node("p",
    `Initial high-intent personas: ${r.spread.organic_adopters}. ` +
    `Later influence-attributed adopters: ${r.spread.influenced_adopters}. ` +
    `Influence-attributed share: ${pct(r.spread.influenced_share)}.`));
  table(social, "Top attributed influencers",
    ["Persona", "Influence trait", "Listeners", "Conversions credited"],
    r.spread.top_influencers.map(i => [
      `${i.name} (${i.persona_id})`, num(i.influence), i.in_degree,
      num(i.conversions_credited)
    ]));

  const events = section("events", "Changes at event rounds",
    "Descriptive before/after changes. Concurrent dynamics can contribute; " +
    "no counterfactual control run is used here.");
  table(events, "Event changes",
    ["Round", "Event", "High-intent change", "Interest change", "Baseline drift"],
    r.events.map(e => [
      e.round, `${e.kind}: ${e.detail}`, pp(e.delta_adoption),
      num(e.delta_interest), pp(e.baseline_drift)
    ]));

  const voices = section("voices", "Synthetic voices",
    "Illustrative generated statements—not interviews with real people.");
  for (const q of r.voices) {
    const details = node("details");
    details.append(node("summary",
      `${q.name} · ${q.segment} · intent ${q.purchase_intent}/5`));
    details.append(node("blockquote", q.text));
    voices.append(details);
  }
  if (!r.voices.length) voices.append(node("p", "No illustrative quotes available."));

  const method = section("methodology", "Methodology and limitations");
  method.append(node("p",
    `Reported ${pct(r.confidence.ci_level)} binomial-bootstrap interval: ` +
    `${pct(r.confidence.adoption_ci_low)}–${pct(r.confidence.adoption_ci_high)}. ` +
    "This interval does not account for LLM bias, audience misspecification, " +
    "network dependence, or real-world calibration error. A zero-width interval " +
    "does not establish certainty."));
  method.append(node("p",
    `Cache-hit ratio: ${r.confidence.cache_hit_ratio === null
      ? "unavailable" : pct(r.confidence.cache_hit_ratio)}. ` +
    "Cache hits measure reuse, not predictive confidence."));
  method.append(node("p",
    "Provider, model, seed, and full scenario details are not present in this Report " +
    "schema. Consult the run manifests. The HTML contains aggregate report data and " +
    "selected synthetic quotes, but no complete population or relationship dataset."));
  method.append(node("p",
    `Generated: ${r.generated_at}. Scenario hash: ${r.scenario_hash}.`, "meta"));

  document.getElementById("print").addEventListener("click", () => window.print());
})();
"""


def _hash_source(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def to_html(report: Report) -> str:
    """Render one offline dashboard; keep complete data in the JSON artifact."""
    bounded = report.model_copy(
        update={"segments": report.segments[:_SEGMENT_LIMIT]}
    )
    payload = json.dumps(
        {
            "report": bounded.model_dump(mode="json"),
            "segment_total": len(report.segments),
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    # Prevent closing the inert script element, even inside generated text.
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    if len(payload.encode("utf-8")) > _MAX_DATA_BYTES:
        raise ValueError("HTML summary exceeds its 2 MB embedded-data budget.")

    policy = (
        "default-src 'none'; base-uri 'none'; form-action 'none'; "
        f"script-src '{_hash_source(_JS)}' '{_hash_source(payload)}'; "
        f"style-src '{_hash_source(_CSS)}'"
    )
    title = escape(report.scenario)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{escape(policy, quote=True)}">'
        f"<title>{title} · Synthetic Society</title>"
        f"<style>{_CSS}</style></head><body><main>"
        '<header><div class="eyebrow">Synthetic Society · Simulation report</div>'
        f"<h1>{title}</h1>"
        '<p class="muted">Explore hypotheses before testing them with real customers.</p>'
        '<nav aria-label="Report sections">'
        '<a href="#overview">Overview</a><a href="#response">Response</a>'
        '<a href="#segments">Segments</a><a href="#pricing">Pricing</a>'
        '<a href="#objections">Objections</a><a href="#social">Social</a>'
        '<a href="#events">Events</a><a href="#methodology">Methodology</a>'
        '</nav><button id="print" type="button">Print / save PDF</button></header>'
        '<noscript><p class="notice">JavaScript is needed for this dashboard. '
        'The adjacent report.md and report.json remain available.</p></noscript>'
        '<div id="dashboard"></div>'
        '<footer>Exploratory synthetic evidence—not a prediction guarantee.</footer>'
        f'<script id="report-data" type="application/json">{payload}</script>'
        f"<script>{_JS}</script></main></body></html>"
    )
