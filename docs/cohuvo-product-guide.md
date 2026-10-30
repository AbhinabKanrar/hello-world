# Cohuvo — Product Guide for Website and Marketing

**Audience for this document:** product, web, and marketing teams.
**Purpose:** a complete, accurate description of what Cohuvo does, how each of its two research modes works, what a customer receives, and what may and may not be claimed about it.
**Status:** describes the implementation on the `develop` branch as of October 2026.

> Every claim in this document is grounded in the current code. Where a capability is planned but not built, it is marked **Planned**. Marketing copy must not promise planned capabilities as current ones.

---

## Part I — The product

### 1. One-paragraph description

Cohuvo is an AI-powered synthetic audience research service. A customer describes an audience (who the people are, in what proportions) and a scenario (what those people are shown and asked). Cohuvo generates a population of synthetic respondents matching that audience, has a large language model answer **as each individual respondent**, and aggregates the answers into a structured, reproducible report with the stated reasons behind them. It is designed for the stage of product work where a team has a concept, a price, or a message and needs a fast, inexpensive read on how a defined audience is likely to react — before, or alongside, research with real people.

### 2. The problem Cohuvo addresses

| Traditional approach | Cost | Time | Limitation |
|---|---|---|---|
| Quantitative survey panel | $5k–$50k+ | 2–6 weeks | Slow iteration; each variant is a new study |
| Focus groups | $5k–$15k per group | 2–4 weeks | Small n; moderator and group effects |
| Concept test via agency | $20k+ | 4–8 weeks | Expensive to re-run after a pivot |
| Internal guesswork | $0 | hours | No structure, no audience definition, no reasons |

Teams iterate on concepts, prices, and messaging far faster than human research can keep up with. Cohuvo fills the gap between "we think" and "we tested with people": a structured, audience-specific read in hours, cheap enough to run on every variant.

### 3. What Cohuvo is — and is not

**Cohuvo is:**
- A way to explore how a *defined* audience distributes across response options to a *specific* question or offer.
- A generator of plausible stated reasons, concerns, and conditions — the "why" behind each answer.
- A tool for comparing variants (two prices, two pitches, two audiences) under identical conditions.
- Reproducible: the same inputs and seed produce the same population and the same cached answers.
- A complement to human research, useful for hypothesis generation, prioritisation, and instrument design.

**Cohuvo is not:**
- A measurement of real human demand, purchases, or trial behaviour.
- A substitute for a representative survey when a decision needs a defensible human number.
- A sales forecast, a price optimiser, or a causal model of word-of-mouth.
- Scientifically validated against human studies in general. (Benchmark comparisons exist and are ongoing; see Part IV.)

A result such as "41% chose *Somewhat likely*" means: *under this audience, scenario, model and settings, 41% of the synthetic respondents selected that option.* It does not mean 41% of the real population would.

### 4. Positioning statement

> **Cohuvo — synthetic audience research for teams that move faster than surveys.**
> Describe your audience. Describe your idea. In hours, see how synthetic respondents matching that audience distribute across the answers — and why.

Secondary lines, all defensible:
- "Explore reactions, reasons and barriers before you spend on human research."
- "Run every variant. Compare prices, pitches and audiences under identical conditions."
- "Structured, reproducible, and honest about what it is: synthetic, exploratory, fast."

### 5. Who it is for

| Segment | Trigger | What they run |
|---|---|---|
| Early-stage founders | Validating a concept and price before building | Simulation (purchase intent + pricing) |
| Product managers | Choosing between positioning or packaging options | Survey (A/B of stimulus wording) |
| Consumer-insights teams | Pre-testing an instrument, or triaging many concepts to pick a few for human research | Survey |
| Marketing | Message testing against defined segments | Survey; Simulation when social spread matters |
| Policy / public-affairs researchers | Exploring stated acceptance of a proposal across demographic groups | Survey with demographic-marginal audiences |
| Agencies | Rapid, repeatable concept screens for clients | Both |

### 6. The two research modes at a glance

Cohuvo has two distinct, independently usable modes. They answer different questions and their numbers are **not interchangeable**.

| | **Independent Survey** | **Social Simulation** |
|---|---|---|
| Question answered | *Given this audience and this exact question, how do respondents distribute across the options, and why?* | *How do synthetic consumers react to a priced product, and how do those reactions change as they talk to each other and events unfold?* |
| Respondents interact | No — each answers once, alone | Yes — modelled social network, peer messages, channel posts |
| Time dimension | Single cross-section | Round 0 exposure + N influence rounds |
| Response scale | **Configurable** — any 2–12 labelled options, operator-defined groups | Fixed: interest (1–5), purchase intent (1–5), max price, objection, would-share |
| Price | Optional, described in the stimulus | Required numeric price; mid-run price changes supported |
| Scenario events | No | Yes — price change, news, competitor, promotion, outage |
| Persona depth | Demographic attributes only | Attributes + behavioural traits + LLM-written biography |
| Commands | 1 | 4 (population → graph → simulation → report) |
| Deliverable | Response distribution, configured groups, stated reasons | Adoption curve, segments, price tolerance curve, objections, spread/influencers, event impact, quotes, narrative |
| Best for | Willingness-to-try, concept acceptance, message testing, benchmark comparisons | Launch dynamics, pricing exploration, word-of-mouth hypotheses |

---

## Part II — Independent Survey

### 7. What it does

The customer defines an audience and a single survey instrument: a stimulus (what the respondent is told), a question, and an ordered list of response options. Cohuvo samples a population matching the audience, asks every synthetic respondent the question once and independently, and reports how many chose each option — with explicit denominators, configurable groupings, and each respondent's stated reason, concern, information need, and the condition that could change their mind.

This is the mode for the product's headline promise: **estimate how a defined audience distributes across willingness-to-try levels, and explain why.**

### 8. Inputs

#### 8.1 Audience (`audience.yaml`)

| Field | Meaning | Example |
|---|---|---|
| `audience` | A plain-English description, shown to the model as context | "Adults 18+ in the US household population, February 2023" |
| `size` | Number of synthetic respondents | 200 – 100,000 |
| `attributes` | Named attributes, each with values and sampling weights | age group, gender, region, income, education, party ID, … |
| `diversity` | Spread of generated behavioural traits (used by Simulation; not shown to the survey model) | `high` |

Attributes support:
- **Categorical** options with relative weights and exclusive selection (`pick: 1`) — e.g. five age bands with census proportions.
- **Multi-select** categorical — e.g. one to three "pain points" per person.
- **Numeric ranges**, uniform or normal — e.g. age 30–45, income 60k–120k.

Weights are relative sampling probabilities. Supplying published population proportions (census, panel codebook) produces a population whose **marginal** distributions approximate the target. Attributes are sampled independently — Cohuvo does not model correlations between them (see Limits).

#### 8.2 Scenario (`scenario.yaml`)

| Field | Meaning |
|---|---|
| `name` | Title for reports |
| `as_of` | Optional date; the model is instructed to answer from that moment and ignore later developments |
| `stimulus` | What the respondent is told — product description, price, terms, eligibility, anything they would see |
| `question` | The exact question |
| `options` | 2–12 options, each with a stable `id`, the exact `label` shown, an optional reporting `group`, and a `nonresponse` flag |

Design principles enforced by the system:
- The exact label wording is what the model sees; nothing is paraphrased.
- Options are a list, not a scale. Cohuvo never assumes the first option is "best" or that an index threshold means "positive". Positive/negative groupings are **declared by the customer** via `group`.
- A *Don't know / refused* option can be offered and is counted separately from substantive answers and from technical failures.
- The model is explicitly instructed not to infer that an unstated price is free, that *trying* means *buying*, or that a trial implies switching; not to invent benefits, guarantees or eligibility rules; and not to target any known poll result.

### 9. How a run works

1. Validate both YAML files against strict schemas; fail loudly on any unknown field.
2. Create a fresh output directory (never overwrite or resume into an existing one).
3. Save the effective inputs and every runtime setting (model, prompt version, seed, temperature) for reproducibility.
4. Sample the population with the given seed.
5. For each respondent, send one structured request: audience text, that person's attributes, the stimulus, the question, the options. The model must return exactly one chosen option plus optional reason / concern / information needed / change condition, in a strictly validated JSON schema.
6. Stream answers to disk as they complete. Provider failures are recorded as *technical failures*, never as answers.
7. Aggregate counts, denominators and groups.
8. If any technical failures occurred, save diagnostics and **withhold** the report. The operator re-runs with `--retry-from`, which reuses every good answer and re-asks only the failed ones.
9. On a clean run, write `report.json` and a `SUCCESS` marker.

Typical wall-clock for 200–1,500 respondents: minutes. Cost per respondent: fractions of a cent with current models.

### 10. Deliverables

| Artifact | Content |
|---|---|
| `report.json` | Requested / completed / valid / nonresponse / technical-failure counts; per-option count, % of completed, % of valid, three example reasons; per-group counts and percentages |
| `responses.jsonl` | Every respondent's chosen option, reason, concern, information needed, change condition |
| `personas.jsonl` | Every respondent's sampled attributes (joinable to responses for segment analysis) |
| `audience.effective.json`, `scenario.effective.json`, `run.settings.json` | The frozen inputs and settings that produced the result |

**Three denominators are always explicit:** `requested` (sampled), `completed` (requested − technical failures), `valid` (completed − nonresponse). This allows like-for-like comparison with human surveys that report either all-respondent or substantive-only percentages.

### 11. Example

The FOOD7 benchmark (AP-NORC, February 2023): *"If meat grown using cells from animals becomes available to purchase in the United States, how likely are you to try it?"* — five likelihood options plus a volunteered-nonresponse category; audience built from the study's published demographic marginals.

A 200-respondent run returns a table such as:

| Option | Count | % of completed |
|---|---:|---:|
| Extremely likely | 0 | 0.0 |
| Very likely | 5 | 2.5 |
| Somewhat likely | 82 | 41.0 |
| Not very likely | 111 | 55.5 |
| Not at all likely | 2 | 1.0 |
| Don't know / refused | 0 | 0.0 |

plus configured groups (Extremely/Very 2.5%, Somewhat 41.0%, Not very/Not at all 56.5%) and example reasons per option. The same table can be placed next to the published human result to evaluate a model and prompt configuration (Part IV).

### 12. Use cases to feature

- **Willingness-to-try screens** for new products, services, formats, or categories.
- **Concept acceptance** across several demographic audiences, run from the same scenario.
- **Message and stimulus A/B**: identical audience and seed, two stimulus wordings, compare distributions and reasons.
- **Price-point framing**: the same offer described at three price points.
- **Instrument pre-test**: see whether options are being used as intended before fielding with humans.
- **Benchmark replication**: approximate a published question and compare — a transparency feature as much as a research one.

### 13. Current limits (state plainly on the website)

- One question per run. No conditional follow-ups, no multi-select questions, no randomised option order. **Planned.**
- Attributes are sampled independently; joint distributions and correlations are not modelled.
- Unweighted aggregation; no post-stratification weights.
- Demographic attributes only in the prompt; no behavioural traits or biographies.
- No automatic segment tables in the report (segment cuts are possible from `responses.jsonl` + `personas.jsonl`). **Planned.**
- Nonresponse is a visible forced-choice option, not a volunteered refusal.
- Answers are the model's stated reasons for a simulated person — not observed human motivation.

---

## Part III — Social Simulation

### 14. What it does

The Social Simulation models a product launch into a population that talks. Each synthetic consumer is given demographic attributes, hidden behavioural traits (openness, price sensitivity, scepticism, social influence, decision style, prospect vs non-buyer), and an LLM-written biography. A social network connects them by similarity and influence. Every consumer is exposed to the product and price in round 0; in later rounds those who hear from peers, see channel posts, or encounter scenario events are re-asked, while everyone else's interest slowly decays. The report shows how simulated purchase intent evolves, who adopts, what they will pay, what blocks them, and how adoption spread through the network.

This is the mode for **launch dynamics, pricing exploration and word-of-mouth hypotheses.**

### 15. Inputs

#### 15.1 Audience — same format as the Survey

With two additional fields that matter here:
- `diversity` (`low` / `medium` / `high`): how widely behavioural traits are spread.
- `non_buyer_share` (0–0.9): share of the population who, by construction, have no intention to participate on this problem — a realism anchor so adoption is not inflated.

#### 15.2 Scenario (`scenario.yaml`)

| Field | Meaning |
|---|---|
| `name` | Title |
| `product` | What it is |
| `pitch` | How it is pitched |
| `price` | `amount`, `period` (one-time / month / year), `currency` — **required** |
| `rounds` | Influence rounds after exposure (0–52) |
| `events` | Timed events: `price_change` (with `new_price`), `news`, `competitor`, `promotion`, `outage` |
| `max_peer_messages`, `max_channel_posts`, `broadcast_top_k`, `decay_every` | Communication and decay settings |

### 16. The four stages

| Stage | Command | What happens | LLM |
|---|---|---|---|
| **1. Population** | `cohuvo population build` | Sample attributes and traits; write a biography, current solution and switching trigger for each persona; detect and regenerate near-duplicate personas using embeddings | Yes |
| **2. Social graph** | `cohuvo graph build` | Build a small-world network: people connect to similar people (homophily), influential people attract more listeners, a share of ties are random long-range links; each tie carries a trust weight; interest channels (friends, reviews, social feed, news) and geographic channels are assigned | No |
| **3. Simulation** | `cohuvo sim run` | Round 0: every persona reacts to the product and price. Rounds 1–N: route peer messages from sharers to listeners, broadcast top sharers to their channels, apply events; re-ask only affected personas; decay the rest; checkpoint each round | Yes |
| **4. Report** | `cohuvo report build` | Aggregate per-round state into the report; cluster objections by meaning; attribute influenced conversions to the neighbours who were sharing; optionally write an executive narrative | Optional |

### 17. What each persona reports (every time they are asked)

| Field | Meaning |
|---|---|
| `interest` 1–5 | Appeal of the idea |
| `purchase_intent` 1–5 | Likelihood to buy at the current price |
| `max_price` | Most they would pay per period; 0 = would not pay |
| `top_objection` | Main blocker in their words |
| `would_share` / `share_message` | Whether, and what, they would tell others — **can be negative** |
| `stance` | One-line current view |
| `reasoning` | Brief explanation |

**Adoption**, throughout the report, means `purchase_intent ≥ 4`. It is simulated stated intent, not purchase.

### 18. Deliverables

`report.json`, `report.md`, and a self-contained offline `report.html` dashboard containing:

| Section | What it shows |
|---|---|
| **Headline** | Final adoption, peak, trend (rising / stable / fading), verdict (strong / promising / weak / dead), with a sampling interval |
| **Adoption curve** | Adoption, mean interest and number of sharers per round, with event markers |
| **Segments** | Adoption and lift for every attribute value and trait bucket; small groups flagged |
| **Price tolerance** | Share willing at each stated price point, median maximum price, share at list price, revenue-maximising simulated price, price-tolerance quartiles |
| **Objections** | Themes clustered by meaning, counts, representative quotes, loudest decision styles |
| **Spread** | Organic vs influenced adopters, share of conversions touched by a channel, top influencers with trust-weighted credit |
| **Event impact** | Change in adoption and interest at each event versus baseline drift |
| **Voices** | Representative adopter and non-adopter quotes from top and bottom segments |
| **Narrative** | Optional LLM-written executive summary and three recommendations, constrained to the computed figures |

A companion guide, [reading-report-json.md](reading-report-json.md), explains every field for analysts.

### 19. Use cases to feature

- **Pre-launch read**: who adopts, who does not, and why, for a priced concept.
- **Pricing exploration**: stated tolerance curve and the effect of a mid-run price change.
- **Word-of-mouth hypotheses**: does the concept generate talk, and is the talk positive?
- **Shock scenarios**: a competitor launch, a bad news story, an outage — how does simulated sentiment respond?
- **Segment prioritisation**: which audience slices show the strongest simulated lift.

### 20. Current limits (state plainly)

- Everything is simulated stated intent; nothing is observed behaviour.
- The price curve is anchored to the prices shown; it is not an independent demand curve.
- Influence attribution is a modelling convention, not causal evidence.
- The sampling interval covers persona-sampling noise only, not model or prompt bias.
- Persona biographies currently assume a US suburban context.
- Enrichment biographies and traits are modelling assumptions.
- Small populations (≤ 50) produce large per-persona swings; recommend ≥ 200 for segment reading.

---

## Part IV — Trust, transparency and validation

### 21. Reproducibility and auditability (strong selling points)

- **Deterministic sampling.** The same audience and seed produce byte-identical populations.
- **Frozen inputs.** Every run stores the effective audience, scenario and all settings, including model and prompt version.
- **Response cache.** Identical requests are served from a local cache: re-running a report costs nothing and yields the same answers; only changed inputs are re-generated.
- **Strict contracts.** Every input and every model output is validated against a typed schema; a malformed answer is corrected or rejected, never silently counted.
- **Explicit denominators and failure accounting.** Technical failures are never counted as answers; nonresponse is never counted as rejection.
- **Fail-closed deliverables.** A report is written only for a complete, failure-free run.
- **Offline deliverables.** The HTML dashboard makes no network calls and embeds no tracking.

### 22. Benchmarking against human studies

Cohuvo can approximate a published survey question — original wording, original option labels, demographic marginals from the study's codebook, a historical `as_of` date — and place its distribution next to the published human result. This is used internally to choose models and prompts, and can be shown to customers as evidence of the method's transparency.

Rules the team follows, and marketing must respect:
- Published results are never placed in the inputs or prompt.
- Agreement on one question with one model is reported as what it is — one comparison — not as validation of the product.
- Discrepancies are reported, not tuned away.
- Models may have seen the published study; a match can reflect memorisation rather than simulation.

**Do not publish benchmark agreement figures as accuracy claims.** Publish them, if at all, as worked examples with the full comparison table and caveats.

### 23. Model and infrastructure

- Models are accessed via OpenRouter with strict JSON-schema output; the current default is `openai/gpt-oss-120b`. Models are evaluated and switched based on benchmark behaviour; a model that hedges toward middle options or breaks character is rejected regardless of price.
- Large populations (tens of thousands or more) can run through the batch API, chunked and bounded, trading latency for throughput. Typical runs use the synchronous path.
- Customer inputs are sent to the model provider for inference. **State this clearly** and describe retention and deletion procedures before accepting confidential concepts.

### 24. Operating model today

Cohuvo is currently **operated by a person**, per customer and per scenario. There is no self-serve portal, API, login, billing system or multi-tenant platform. Every deliverable is reviewed by the operator before it reaches the customer: numbers, charts, quotes, narrative and interpretation.

For the website this means: **"Request a run" / "Book a study"**, not "Sign up". Marketing should sell a service with a human in the loop, which is also a trust advantage.

---

## Part V — Guidance for website and campaigns

### 25. Messaging that is accurate

| Say | Because |
|---|---|
| "Synthetic audience research" | Exactly what it is |
| "Explore how a defined audience is likely to respond — and why" | Distribution + reasons, the core deliverable |
| "In hours, not weeks" | True for typical sizes |
| "Run every variant" | Cheap, reproducible, cached |
| "Honest about uncertainty" | Explicit denominators, intervals, failure accounting |
| "A complement to human research" | Positioning that survives scrutiny |
| "Human-reviewed deliverables" | Current operating model |

### 26. Messaging that is not accurate — do not use

| Avoid | Why |
|---|---|
| "Predicts what customers will do" / "sales forecast" | Measures synthetic stated responses only |
| "Optimal price" | Price curve is anchored and exploratory |
| "Replaces surveys / focus groups" | It complements them |
| "Validated against human data", "X% accurate" | Not established; one benchmark ≠ validation |
| "Representative sample" | Marginals approximated, correlations not modelled, unweighted |
| "Margin of error ±N%" borrowed from a human study | Does not transfer |
| "Real consumers", "real opinions" | They are synthetic |
| "Instant" / "real-time" | Minutes to hours depending on size |
| "Self-serve platform", "API", "dashboard login" | Not built |
| Quoting a synthetic respondent as if a person | Always label as synthetic |

### 27. Suggested site structure

1. **Home** — positioning line, 3 proof points (hours not weeks; reasons not just numbers; reproducible and transparent), the two modes as cards, "Request a run".
2. **How it works** — audience → scenario → synthetic respondents → report, with the two-mode comparison table from Section 6.
3. **Independent Survey** — Part II condensed; sample report table; use cases; limits.
4. **Social Simulation** — Part III condensed; dashboard screenshots; use cases; limits.
5. **Trust & method** — Part IV: reproducibility, denominators, fail-closed, benchmark approach, data handling, human review. This page is a differentiator; do not bury it.
6. **Examples** — anonymised or public-benchmark runs with the full comparison table and caveats.
7. **Pricing / engagement** — per-study engagement; what is included (inputs review, run, review, deliverables, debrief).
8. **FAQ** — Section 29.

### 28. Campaign angles

- **"Before you field it, synth it."** Pre-test instruments and concepts.
- **"Every variant, every audience, same conditions."** The reproducibility angle for PMs and marketers.
- **"We show the denominators."** Transparency as a brand value, aimed at insights professionals who are sceptical of AI research.
- **"The why, not just the what."** Reasons, concerns, information needs, change conditions — per respondent.
- **"Launch dynamics you can rehearse."** Simulation: price shocks, bad news, competitor entry.

### 29. FAQ (ready to publish)

**Are these real people?** No. Respondents are synthetic — generated from the audience you define and answered by an AI model role-playing each one.

**How accurate is it?** Cohuvo does not claim to predict human behaviour. It shows how synthetic respondents matching your audience distribute across answers under stated conditions, and why. We benchmark configurations against published human studies and publish the comparisons with their caveats.

**What do I need to provide?** A description of your audience with proportions for the attributes that matter, and the stimulus, question and options (Survey) or the product, pitch, price and timeline (Simulation).

**How long does a run take?** Typically minutes to a few hours depending on population size and mode.

**Can I compare two versions?** Yes — same audience and seed, different stimulus or price. Only the changed answers are regenerated.

**Can I see individual responses?** Yes. Every respondent's answer and stated reasons are delivered alongside the aggregate report.

**Is my concept confidential?** Inputs are processed by a third-party model provider for inference. We explain the exact data flow, retention and deletion before any confidential run.

**Can I run it myself?** Not yet. Each study is run and reviewed by a Cohuvo operator.

**Can it replace my survey?** No. Use it to explore, prioritise and pre-test; field human research for decisions that need a defensible human number.

---

## Part VI — Glossary

| Term | Meaning |
|---|---|
| Audience | The customer's definition of who the respondents are and in what proportions |
| Scenario | What respondents are shown and asked (Survey) or the product, price, rounds and events (Simulation) |
| Persona / respondent | One synthetic person with sampled attributes (and, in Simulation, traits and a biography) |
| Seed | Integer controlling sampling and generation; same seed + same inputs = same result |
| Option | One labelled answer in a Survey; order is instrument order, not a scale |
| Group | Customer-defined aggregate of options (e.g. "Extremely/Very likely") |
| Nonresponse | A *Don't know / refused* option, counted separately from substantive answers |
| Technical failure | A model request that failed; never counted as an answer; blocks the deliverable until retried |
| Requested / completed / valid | The three survey denominators |
| Adoption (Simulation) | Share with purchase intent ≥ 4 |
| Round | One step of the Simulation; round 0 is first exposure |
| Decay | Loss of interest for personas not re-engaged |
| Lift | Segment adoption ÷ overall adoption |
| Influenced adopter | A persona whose first adoption followed peer or channel exposure |
| Stated reason | The model's explanation on behalf of a synthetic respondent — not observed motivation |
