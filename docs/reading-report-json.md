# Reading the four-stage `report.json`

This guide explains the `report.json` produced by:

```text
population build → graph build → sim run → report build
```

It covers what each field means, how it is calculated, how the sections relate, and how to present them in a report. Examples use the 25-persona **MealMind launch** run in [`report.json`](../report.json).

> This guide is for the four-stage simulation report only. `cohuvo survey run` writes a different `report.json` (`TrialReport`) with no rounds, social graph, or price curve.

---

## 1. Concepts used throughout

| Concept | Definition | Code |
|---|---|---|
| Persona | One synthetic person from `personas.jsonl`. | [`schemas.py`](../src/society/schemas.py) |
| Round | Round `0` is first exposure. Later rounds are peer influence, channel posts, and events. | [`engine.py`](../src/society/sim/engine.py) |
| Interest | Persona's appeal score, `1`–`5`. Not a purchase signal. | [`sim/schemas.py`](../src/society/sim/schemas.py) |
| Purchase intent | Persona's likelihood to buy, `1`–`5`. | [`sim/schemas.py`](../src/society/sim/schemas.py) |
| **Adopter** | Purchase intent **≥ 4**. Every adoption figure uses this cutoff. | `ADOPT_THRESHOLD` in [`frame.py`](../src/society/report/frame.py) |
| Max price | Persona's stated maximum price per period; `0` means they would not pay. | [`sim/schemas.py`](../src/society/sim/schemas.py) |
| Sharing | Persona wants to talk about the product. **The message can be negative.** | [`state.py`](../src/society/sim/state.py) |
| Decay | Personas not re-asked lose one interest point every `decay_every` rounds (default 2). Intent is capped at interest, and they stop sharing. | [`state.py`](../src/society/sim/state.py) |

### Carry-forward rule

Only personas who receive new messages or events are re-asked in each round. Everyone else keeps their previous answer, with possible decay. Each round therefore describes **all 25 personas**, not only those asked that round.

### Final round vs all rounds

| Uses every round | Uses **final round only** |
|---|---|
| `curve`, `headline`, `events`, `spread` | `segments`, `price`, `objections`, `voices`, `confidence` |

This explains why the curve can show a dip while the segment and price sections only describe the end state.

### Data flow

```text
personas.jsonl ──────────┐
graph/ ──────────────────┤
sim/events.jsonl ────────┼─► Frame (persona × round matrices) ─► metrics ─► report.json
sim/sim.manifest.json ───┤                                       │
scenario.yaml ───────────┘                                       ├─► report.md
                                                                 └─► report.html
```

The report is deterministic for the same simulation output and seed, except for the optional LLM-written `narrative`. Objection grouping also uses embeddings when the report runs with an LLM client.

---

## 2. Top-level fields

| Field | Meaning |
|---|---|
| `scenario` | Scenario name from `scenario.yaml`. |
| `scenario_hash` | Hash of the scenario. The report refuses to build if it does not match the simulation. |
| `generated_at` | UTC time the report was built, not the time of the simulation. |

---

## 3. `headline` — the verdict

```json
"headline": {
  "final_adoption": 0.32, "peak_adoption": 0.32, "peak_round": 2,
  "trend": "rising", "verdict": "promising"
}
```

| Field | Calculation | Example |
|---|---|---|
| `final_adoption` | Adopters in the last round ÷ all personas. | 32% = 8 of 25 |
| `peak_adoption` | Highest adoption in any round. | 32% |
| `peak_round` | **First** round reaching the peak. | Round 2; round 5 ties |
| `trend` | Final adoption minus adoption two rounds earlier: `> +0.01` rising, `< −0.01` fading, otherwise stable. | 32% − 20% (round 3) → rising |
| `verdict` | Final adoption only: ≥35% strong, ≥20% promising, ≥8% weak, otherwise dead. | 32% → promising |

**Relationship:** `headline` is a summary of `curve`. `verdict` ignores `confidence`. In this run, the interval is 16–52%, which spans "weak" through "strong".

### Show it as

- A headline card: **Promising — 32% adoption (8 of 25), 95% interval 16–52%.**
- Show the interval next to the verdict so the label is not read as certain.

---

## 4. `curve` — adoption over time

One entry per round.

| Field | Meaning |
|---|---|
| `round` | Round number. |
| `adoption` | Share of all personas with intent ≥ 4. |
| `mean_interest` | Average interest across all personas (1–5). An early signal; can rise before adoption. |
| `sharers` | Personas **currently** willing to talk about the product. Includes negative talk. |
| `event` | Scenario event applied in that round, if any. |

### Example

| Round | Adoption | Interest (1–5) | Talking about it | Event |
|---|---:|---:|---:|---|
| 0 | 8% (2) | 2.68 | 2 (8%) | — |
| 1 | 16% (4) | 2.60 | 11 (44%) | — |
| 2 | **32% (8)** | **3.40** | 13 (52%) | — |
| 3 | 20% (5) | 2.80 | 14 (56%) | Price raised to $19 |
| 4 | 24% (6) | 3.16 | 15 (60%) | Viral TikTok on repetitive meals |
| 5 | 32% (8) | 3.20 | 18 (72%) | — |

### Reading it

- Sharers jump in round 1, before adoption doubles in round 2: word of mouth leads conversion.
- Interest higher than adoption means people like the idea but are blocked by something, such as price or trust.
- **Sharing is not advocacy.** Round 5 has 18 sharers and 8 adopters, so at least 10 sharers are non-adopters.
- With 25 personas, one person is 4 percentage points. Avoid reading small changes as trends.

### Show it as

- Line chart: adoption on the left axis and interest on a 1–5 right axis.
- Faint bars for sharers, labelled **"Talking about it (positive or negative)"**.
- Dashed vertical markers at event rounds.
- Table with counts and percentages, such as `8 of 25 (32%)`.

---

## 5. `segments` — who it works for

Each row compares one group with the whole population, using **final-round** values. Overall adoption is 32%.

| Field | Meaning |
|---|---|
| `dimension` | Trait used to group personas. |
| `bucket` | Value of that trait. Numeric traits are split into four quantile ranges. |
| `n` | Personas in the bucket. |
| `adoption` | Share of the bucket with intent ≥ 4. |
| `mean_intent` | Average final purchase intent (1–5). |
| `lift` | `segment adoption ÷ overall adoption`. `1.0` is average. |
| `low_n` | `true` when `n < 10`. Treat as too small to call. |

Rows are sorted reliable groups first, then by lift.

### Dimension types

| Type | Examples | Note |
|---|---|---|
| Audience attributes | `age`, `household_income`, `kids`, `tech_comfort`, `employment`, `pain_points` | Directly targetable. |
| Simulated traits | `decision_style`, `segment`, `price_sensitivity` | Generated by the sampler; explain behaviour but are harder to target. |

### Example: reliable rows

| Group | n | Adoption | Intent | Lift |
|---|---:|---:|---:|---:|
| High tech comfort | 15 | 46.7% | 3.07 | **1.46×** |
| Prospects | 19 | 42.1% | 2.95 | 1.32× |
| Low price sensitivity | 12 | 41.7% | 2.58 | 1.30× |
| Part-time | 11 | 36.4% | 2.73 | 1.14× |
| Pain point: rising grocery bills | 11 | 36.4% | 2.73 | 1.14× |
| Age 42–45 | 10 | 30.0% | 2.80 | 0.94× |
| 2–3 kids | 17 | 29.4% | 2.47 | 0.92× |
| Full-time | 17 | 29.4% | 2.71 | 0.92× |
| Medium tech comfort | 22 | 27.3% | 2.50 | 0.85× |
| Researchers | 11 | 18.2% | 2.27 | **0.57×** |

### Reading it

- **Adoption with intent:** high intent and low adoption means many people are at 3/5 and could convert with a trial. Low values for both means the group is far from buying.
- `segment = non_buyer` should be near 0%; here it is 0% with intent 1.5, which is a useful sanity check.

### Cautions

1. **Small groups:** at `n = 15`, one persona moves adoption by about 7 points. `n ≥ 10` is a display threshold, not statistical significance.
2. **Overlapping buckets:** list attributes put one persona in several buckets. `tech_comfort` high (15) + medium (22) = 37 for a population of 25. Do not add counts or present them as population shares.
3. **Shared range edges:** labels such as `1–2` and `2–3` share a boundary. Relabel them clearly.
4. **Hidden rows:** 27 of 37 rows are `low_n`. Several show 50% adoption from 2–6 people; do not promote them.

### Show it as

- Horizontal lift chart for reliable rows, with a reference line at **1.0×**.
- Split into **"Who it's working for"** (lift > 1.1) and **"Who it isn't reaching"** (lift < 0.9).
- Plain-language labels; group simulated traits under **"Simulated traits"**.
- Collapsed **"Too small to call (n<10)"** section without bars or recommendations.
- Footnote: groups can overlap; differences are directional.

---

## 6. `price` — willingness to pay

Uses each persona's **final** stated maximum price. This measures **price tolerance, not demand**: a persona can tolerate $20 and still have intent 1.

| Field | Meaning | Example |
|---|---|---|
| `points[]` | Up to 40 prices from the answers. | 19 points, $1–$30 |
| `points[].price` | Test price. | 19 |
| `points[].share_willing` | Share of **all** personas whose max price is at least this price. | 0.76 |
| `points[].revenue_index` | `price × share_willing`. Relative, not dollars; ignores costs. | 14.44 |
| `share_unwilling` | Share whose max price is 0. | 4% (1) |
| `median_max_price` | Median, **excluding zero answers**. | $20 |
| `list_price` | Scenario's **starting** price; ignores later price changes. | $15 |
| `list_price_share` | Share willing at `list_price`. | 76% |
| `revenue_max_price` | Price with the highest `revenue_index`. | $19 |
| `revenue_max_share` | Share willing at that price. | 76% |
| `suggested_tiers` | 25th, 50th, and 75th percentiles of nonzero answers. Not designed pricing tiers. | $19, $20, $21.25 |

### Example in counts

| Price | Would pay | Share |
|---|---:|---:|
| $1 | 24 | 96% |
| $12 | 21 | 84% |
| $15 / $19 | 19 | 76% |
| $20 | 15 | 60% |
| **$20.51** | **6** | **24%** |
| $30 | 3 | 12% |

### Reading it

- **Anchoring:** about 13 of 24 paying personas named roughly $19–$20, after seeing $19 from round 3. Treat values near the shown price as weak evidence.
- **Threshold:** willingness drops from 60% to 24% just above $20. This is the clearest pricing signal.
- **Revenue maximum** mostly reflects the shown price, not an independent optimum.
- **Price tolerance is not the bottleneck:** 76% accept $19, but only 32% adopt.
- **Price shock vs tolerance:** moving from $15 to $19 cost no tolerance on the final curve, yet adoption fell from 32% to 20% in round 3.

### Show it as

- Step chart: price on the x-axis and share willing on the y-axis, with markers for **Launch $15**, **Current $19**, and the **$20 drop**.
- Optional faint revenue-index line, labelled "relative; ignores costs".
- Rename `suggested_tiers` to **"Price-tolerance quartiles"**.
- Show both the starting and current price.
- Footnote: stated maximums; likely anchored to the shown price.

---

## 7. `objections` — what holds people back

Built from each persona's **final** `top_objection`, including adopters.

### How themes are made

1. Normalise text (lowercase, trim whitespace and trailing punctuation).
2. Deduplicate.
3. With an LLM client: embed unique strings and group them when similarity ≥ 0.82. Without a client: exact matches only.
4. Keep the 8 largest themes; the rest become `Other`.

| Field | Meaning |
|---|---|
| `label` | Most frequent text in the theme, used as its name. With all counts tied, it is effectively arbitrary. |
| `count` | Personas in the theme. |
| `share` | `count ÷ all personas`. Themes plus `Other` sum to 100%. |
| `quotes` | Up to 3 distinct original texts. |
| `top_segments` | Two most common **decision styles** in the theme, with counts. |

### Example

| Theme | Count | Share | Loudest |
|---|---:|---:|---|
| Potential repetition / limited variety | 6 | 24% | asks-friends (3), researcher (2) |
| $19 too high plus repetition | 4 | 16% | researcher (3), impulsive (1) |
| Want proof of grocery savings | 2 | 8% | asks-friends, researcher |
| Occasional repetition | 2 | 8% | impulsive, loyalist |
| Savings and variety doubts | 2 | 8% | asks-friends, researcher |
| High cost without trial or proof | 1 | 4% | asks-friends |
| Need data on cost and recipes | 1 | 4% | researcher |
| May repeat meals; cost risky | 1 | 4% | asks-friends |
| Other | 6 | 24% | — |

### Reading it

- **Similar themes may be split.** Labels mentioning repetition or variety cover 15 of 25 personas across five themes. Merge related themes manually before presenting.
- Read `quotes`, not only `label`.
- `top_segments` uses decision style only; it does not show income, age, or other dimensions.
- Adopters also report objections. A theme is a concern, not necessarily a blocker.

### Show it as

- Ranked horizontal bars of merged themes, labelled by count and percentage.
- One or two representative quotes per theme.
- Separate **"Blockers"** from **"Concerns among adopters"** when the data is available from `events.jsonl`.
- Footnote: themes are grouped automatically.

---

## 8. `spread` — how adoption travelled

| Field | Meaning | Example |
|---|---|---|
| `organic_adopters` | Personas whose **first** adoption was in round 0. | 2 |
| `influenced_adopters` | Personas whose first adoption was later, after influence. | 11 |
| `influenced_share` | `influenced ÷ all personas who ever adopted`. | 84.6% |
| `channel_touched_share` | Influenced adopters who received a channel post when they converted. | 90.9% (10 of 11) |
| `top_influencers[]` | Up to 10 personas credited with conversions. | — |

### `top_influencers[]`

| Field | Meaning |
|---|---|
| `index`, `persona_id`, `name` | Persona identity. |
| `influence` | Persona's influence trait, 0–1. |
| `in_degree` | Number of personas who listen to them in the graph. |
| `conversions_credited` | Fractional credit. Each influenced adopter splits one credit among neighbours it listens to who shared in the previous round, weighted by trust. |

### Reading it

- **Ever adopted vs final adopters:** `2 + 11 = 13` personas adopted at some point, but only 8 are adopters at the end. **Five dropped out.** This is not visible in `headline`.
- **Influence matters:** 85% of first adoptions followed peer or channel exposure.
- **Credit is attribution, not proof.** Neighbours get credit for sharing, even if their message was negative.
- **Influence trait and credit differ.** Megan Alvarez has influence 0.06 but 1.1 credited conversions, because she was sharing when personas who listen to her converted.

### Example

| Influencer | Influence | Listeners | Credit |
|---|---:|---:|---:|
| Lena Whitaker | 0.96 | 16 | 3.9 |
| Alexis Ramirez | 0.94 | 14 | 1.7 |
| Megan Alvarez | 0.06 | 9 | 1.1 |

### Show it as

- Small flow or funnel: **2 organic → 11 influenced → 13 ever adopted → 8 at final round**.
- Top-5 influencer table with listeners and credited conversions.
- Takeaway: *"Growth depended on word of mouth; one persona received about 35% of the credit for influenced conversions."*

---

## 9. `events` — what changed at each scenario event

| Field | Meaning |
|---|---|
| `round`, `kind`, `detail` | Event from the scenario. |
| `delta_adoption` | Adoption change from the previous round. |
| `delta_interest` | Interest change from the previous round. |
| `baseline_drift` | Average adoption change in rounds **without** events. |
| `notable` | `true` when `abs(delta_adoption − baseline_drift) ≥ 0.02`. |

### Example

Baseline drift is the mean of rounds 1, 2, and 5: `(+8 + 16 + 8) ÷ 3 = +10.7 pp`.

| Round | Event | Change | Versus normal growth |
|---|---|---:|---:|
| 3 | Price raised to $19 | −12 pp | **−22.7 pp** |
| 4 | Viral TikTok on repetition | +4 pp | **−6.7 pp** |

### Reading it

- Compare `delta_adoption` with `baseline_drift`, not with zero. The TikTok round still grew, but by less than normal.
- At 25 personas, one person is 4 pp and the threshold is 2 pp, so almost every event is `notable`.
- The comparison is not causal. Events in consecutive rounds overlap with carry-over effects.

### Show it as

- Annotated markers on the adoption chart.
- Small table: event, change, normal growth, difference.
- Do not label an event "notable" without the sample-size caveat.

---

## 10. `voices` — representative quotes

Up to 6 personas:

- One **adopter** with the highest intent from each of the top 3 reliable segments.
- One **non-adopter** with the lowest intent from each of the bottom 3 reliable segments.
- A persona appears at most once.

| Field | Meaning |
|---|---|
| `persona_id`, `name` | Persona. |
| `segment` | Segment the quote was selected for. Not the persona's only trait. |
| `purchase_intent` | Final intent. |
| `text` | Persona's latest reasoning. |

### Example

| Name | Picked for | Intent |
|---|---|---:|
| Lena Morales | High tech comfort | 5 |
| Megan Ortiz | Prospect | 5 |
| Megan Alvarez | Low price sensitivity | 4 |
| Jordan Blake | Full-time | 1 |
| Jordan Liu | Medium tech comfort | 1 |
| Jenna Ortega | Researcher | 1 |

### Quality checks

Read every quote before publishing:

- **Product claims may be invented.** Quotes mention a free trial, loyalty-program sync, and 15–20% savings, none of which are in the scenario. Peer messages can spread those claims.
- **Text and score can disagree.** Jordan Liu's quote reads positively but has intent 1.
- **Inconsistent voice or truncation.** Jenna Ortega's text is third person, and Lena Morales's ends mid-sentence.

### Show it as

- Quote cards split into **Why they'd buy** and **Why they wouldn't**, showing name, segment, and intent.
- Exclude or flag quotes with invented features or score mismatches.

---

## 11. `confidence` — how much to trust the headline

| Field | Meaning | Example |
|---|---|---|
| `n` | Personas. | 25 |
| `rounds` | Influence rounds after round 0. | 5 |
| `ci_level` | Interval level. | 0.95 |
| `adoption_ci_low`, `adoption_ci_high` | Bootstrap interval for final adoption. | 16%–52% |
| `cache_hit_ratio` | Reused cached responses ÷ LLM calls. Affects cost, not results. | 0 |

### Reading it

- The interval covers **sampling noise only**. It does not cover model, prompt, or seed bias.
- A 16–52% interval is wide. Increase population size or repeat seeds before making decisions.

### Show it as

- Error bar on the headline adoption figure.
- Methodology note: **"Synthetic personas, not measured human demand."**

---

## 12. `narrative` — LLM summary

| Field | Meaning |
|---|---|
| `summary` | Summary written by the configured chat model. The prompt asks for 120–200 words; validation accepts 100–250. |
| `recommendations` | Exactly 3 distinct recommendations of 20–300 characters each. |

The model receives only `headline`, top/bottom reliable segments, price summary, top objections, and events. It does **not** receive `confidence`, `spread`, or `voices`.

Placeholder text (`...`, `…`, `(truncated)`, `TBD`, `TODO`) or empty recommendations fail validation. The validation errors are sent back to the model to correct. If retries still fail, `narrative` is `null` and the log contains `narrative_failed`. The other sections are still written.

> This example was generated before that validation existed, so it contains placeholders (`"..."` and empty strings). Rebuild the report to replace them.

### Show it as

- Executive summary near the top, labelled **AI-generated**.
- Check every number in it against the fields above.

---

## 13. Field quick reference

| Path | One-line meaning |
|---|---|
| `headline.final_adoption` | Share with intent ≥ 4 at the end |
| `headline.verdict` | Label from final adoption only |
| `curve[].mean_interest` | Average 1–5 interest |
| `curve[].sharers` | Personas talking about it, positive or negative |
| `segments[].lift` | Segment adoption ÷ overall adoption |
| `segments[].low_n` | Fewer than 10 personas |
| `price.points[].share_willing` | Share whose max price ≥ price |
| `price.list_price` | **Starting** price |
| `price.suggested_tiers` | Quartiles of stated max price |
| `objections[].top_segments` | Top decision styles in the theme |
| `spread.influenced_share` | Influenced ÷ ever adopted |
| `spread.top_influencers[].conversions_credited` | Trust-weighted credit |
| `events[].baseline_drift` | Normal growth in rounds without events |
| `voices[].segment` | Segment the quote was picked for |
| `confidence.adoption_ci_*` | Sampling interval for final adoption |
| `narrative` | LLM-written summary |

---

## 14. Recommended report layout

1. **Headline card** — verdict, adoption with interval, and one-sentence takeaway.
2. **Executive summary** — checked narrative and recommendations.
3. **Adoption over time** — curve chart with event markers.
4. **Who it works for** — segment lift chart.
5. **Pricing** — tolerance curve with the anchoring caveat.
6. **What holds people back** — merged objection themes with quotes.
7. **How it spread** — funnel and top influencers.
8. **Event impact** — comparison against normal growth.
9. **Voices** — checked buyer and non-buyer quotes.
10. **Methodology and limits** — sample size, synthetic personas, interval, and model.

### Example takeaway for this run

> MealMind is **promising but uncertain**: 32% of 25 personas adopted (95% interval 16–52%). It works best with tech-comfortable, less price-sensitive households and relies heavily on word of mouth. The $19 price increase cut adoption sharply, and recipe repetition is the most common concern. Personas tolerate up to about $20, so trust and variety matter more than price.

---

## 15. Existing renderers

| File | Output | Notes |
|---|---|---|
| [`render.py`](../src/society/report/render.py) | `report.md` | Raw tables. Labels `list_price` and `suggested_tiers` in a way that can mislead. |
| [`html.py`](../src/society/report/html.py) | `report.html` | Self-contained dashboard, no network calls. |
| [`builder.py`](../src/society/report/builder.py) | All three files | `ReportBuilder.write()` writes JSON, Markdown, and HTML. |

Regenerate all outputs with:

```bash
cohuvo report build --personas out/personas.jsonl --graph out/graph --sim out/sim \
  --scenario examples/scenario.yaml --seed 42 --out-dir out/report
```
