# Reading the survey `report.json`

This guide explains the `report.json` produced by:

```text
cohuvo survey run --audience audience.yaml --scenario scenario.yaml --seed N --out-dir DIR
```

It covers what each field means, how it is calculated, how to check that a run is sound, and how to evaluate the result against a human benchmark. Examples use the 200-persona **FOOD7** run in [`survey.json`](survey.json), produced with `anthropic/claude-haiku`.

> This guide is for the survey report (`trial-report-v1`) only. The four-stage pipeline writes a different `report.json`; see [reading-report-json.md](reading-report-json.md).

---

## 1. Concepts used throughout

| Concept | Definition | Code |
|---|---|---|
| Respondent | One synthetic person from `personas.jsonl`. Only the audience description and sampled **attributes** are shown to the model; generated traits and biographies are not. | [`prompts.py`](../src/society/sim/prompts.py) |
| Option | One configured response in `scenario.yaml`, with `id`, `label`, optional `group`, and `nonresponse` flag. | [`sim/schemas.py`](../src/society/sim/schemas.py) |
| `option_index` | Position of the chosen option in the configured list, starting at 0. **A lookup index, not a score.** | [`sim/schemas.py`](../src/society/sim/schemas.py) |
| Nonresponse | An option flagged `nonresponse: true` (for example *Don't know / refused*). A real answer, counted separately from substantive ones. | [`metrics.py`](../src/society/report/metrics.py) |
| Technical failure | The LLM request failed after retries. **Not an answer** of any kind. | [`engine.py`](../src/society/sim/engine.py) |
| Group | A reporting bucket that sums several options, defined by `group` on each option. | [`metrics.py`](../src/society/report/metrics.py) |

### One question, one answer, no interaction

Every respondent is asked the same question once, independently, at `temperature 0.7`. There are no rounds, no peer messages, no social graph, no decay, and no price model. The report describes a single cross-section.

### Three denominators

| Denominator | Definition | Use it for |
|---|---|---|
| `requested` | Personas sampled (`size` in `audience.yaml`). | Checking completeness. |
| `completed` | `requested − technical_failures`. Includes nonresponse selections. | Comparing with a human poll's **all-respondents** percentages. |
| `valid` | `completed − nonresponse`. Substantive answers only. | Comparing with a poll that reports percentages **excluding** don't-know/refused. |

Mixing these up is the most common mistake when comparing with a published study.

### Data flow

```text
audience.yaml ──► PopulationSampler ──► personas.jsonl
                                             │
scenario.yaml ──► trial_prompt ──► LLM (one call per persona) ──► responses.jsonl
                                                                        │
                                                          summarize_trial ─► run.summary.json
                                                                        └─► report.json + SUCCESS
```

`report.json` and `run.summary.json` have identical content. The difference is **when** they exist: `run.summary.json` is always written; `report.json` and `SUCCESS` are written only when `technical_failures == 0`.

---

## 2. Output directory

| File | Purpose | Written when |
|---|---|---|
| `audience.effective.json` | Parsed audience, after shorthand expansion. | Always |
| `scenario.effective.json` | Parsed survey instrument. | Always |
| `run.settings.json` | Seed, prompt version, persona mode, temperature, and all settings (API key excluded). | Always |
| `personas.jsonl` | Sampled respondents, one per line. | Always |
| `responses.jsonl` | One `TrialRecord` per respondent, in index order. The complete raw data. | Always (possibly partial on crash) |
| `run.summary.json` | Aggregates, even for failed runs. Diagnostic, not a deliverable. | After all responses |
| `report.json` | The deliverable. | Only if zero technical failures |
| `SUCCESS` | Completion marker. | Last, only on success |
| `recovery.source.json` | Present when the run was started with `--retry-from`. | Retry runs only |

**Rule:** no `SUCCESS`, no deliverable. A directory with `run.summary.json` but no `report.json` had failures; rerun with `--retry-from DIR` into a fresh directory.

---

## 3. Top-level fields

```json
"schema_version": "trial-report-v1",
"scenario": "FOOD7 — Likelihood of trying meat grown using animal cells",
"scenario_hash": "e2b586…",
"generated_at": "2026-10-29T20:45:09.250497Z",
"requested": 200, "completed": 200, "valid": 200,
"nonresponse": 0, "technical_failures": 0
```

| Field | Meaning | Check |
|---|---|---|
| `schema_version` | Report format. | Must be `trial-report-v1`. |
| `scenario` | `name` from `scenario.yaml`. | — |
| `scenario_hash` | SHA-256 of the parsed scenario. | Identical across runs that should be comparable. A different hash means the instrument changed. |
| `generated_at` | UTC time the report was built. | Not the date the respondents were "asked"; that is `as_of` in the scenario. |
| `requested` | Personas sampled. | Equals `size` in `audience.yaml`. |
| `completed` | Successful structured answers. | `requested − technical_failures`. |
| `valid` | Substantive answers. | `completed − nonresponse`. |
| `nonresponse` | Respondents who chose a `nonresponse: true` option. | — |
| `technical_failures` | LLM calls that failed. | **Must be 0** in a deliverable. |

### Arithmetic that must hold

```text
requested  = completed + technical_failures
completed  = valid + nonresponse
completed  = Σ categories[].count         (all categories, including nonresponse)
valid      = Σ categories[].count         (where nonresponse == false)
```

Example: `200 = 200 + 0`, `200 = 200 + 0`, `0 + 5 + 82 + 111 + 2 + 0 = 200`. ✔

---

## 4. `categories` — the response distribution

One entry per configured option, **in scenario order**.

| Field | Meaning |
|---|---|
| `id` | Option `id` from `scenario.yaml`. Stable key for scripts. |
| `label` | Exact wording shown to the respondent. |
| `count` | Respondents who chose this option. |
| `nonresponse` | Whether this option is the nonresponse category. |
| `percent_completed` | `count ÷ completed × 100`. `null` if `completed == 0`. |
| `percent_valid` | `count ÷ valid × 100`. `null` for the nonresponse option, or if `valid == 0`. |
| `reason_examples` | First **three** non-null `reason` texts for this option, in respondent order. |

### Example

| Option | Count | % completed | % valid |
|---|---:|---:|---:|
| Extremely likely | 0 | 0.0 | 0.0 |
| Very likely | 5 | 2.5 | 2.5 |
| Somewhat likely | 82 | 41.0 | 41.0 |
| Not very likely | 111 | 55.5 | 55.5 |
| Not at all likely | 2 | 1.0 | 1.0 |
| Don't know / skipped / refused | 0 | 0.0 | — |

Here `% completed` and `% valid` coincide because there was no nonresponse.

### Reading it

- **The shape matters more than any single number.** A population of real people spreads across options; a model that hedges piles into the middle. In this run 96.5% of answers sit in two adjacent middle options and both endpoints are nearly empty.
- **Tail mass** (`Extremely likely + Not at all likely`) is the quickest health indicator: 1.0% here against 34.6% in the human study (Section 8).
- **Option order is instrument order, not an acceptance scale.** Do not assume index 0 is "best" or that index ≥ 3 is "negative"; use `groups` for that.
- **Zero nonresponse is common** and expected: the model must pick exactly one option from a strict schema, and a visible "don't know" is chosen far less often than humans volunteer it. Do not read it as higher engagement.

### `reason_examples` — what they are and are not

They are the first three reasons encountered, not the most common and not ranked. Use them as a **quality check**, not as evidence of why people answered:

| Check | What to look for | Example from this run |
|---|---|---|
| Consistency | Does the reason match the option? | "fairly eager to try" filed under *Very likely* — consistent. |
| Point of view | First person ("I would…"), not an analyst describing the respondent. | "Based on the respondent's very conservative views…" — **broke character**. |
| Invented facts | Prices, safety approvals, experiences, diets not in the stimulus. | None visible, but check `responses.jsonl`. |
| Templating | Near-identical phrasing across respondents. | "I'd want to see how it tastes and what it costs" recurs — attributes are not driving variation. |
| Placeholder text | `...`, `N/A`, `none` as strings. | None here. |

For a real picture of reasons, read `responses.jsonl` (Section 7), where every answer carries `reason`, `concern`, `information_needed`, and `change_condition`.

### Show it as

- Horizontal bars in instrument order, labelled with count and `% completed`, nonresponse bar visually separated.
- If comparing with a benchmark, pair each bar with the benchmark value (Section 8).
- State the denominator in the axis title: "% of 200 completed responses".

---

## 5. `groups` — configured aggregates

One entry per distinct `group` value in `scenario.yaml`, in first-appearance order. Options with `group: null` (including nonresponse) are not in any group.

| Field | Meaning |
|---|---|
| `id`, `label` | The group name (both equal the `group` string). |
| `count` | Sum of member option counts. |
| `percent_completed` | `count ÷ completed × 100`. |
| `percent_valid` | `count ÷ valid × 100`. |
| `nonresponse` | Always `false`. |
| `reason_examples` | Always empty for groups. |

### Example

| Group | Members | Count | % completed |
|---|---|---:|---:|
| Extremely/Very likely | 0 + 5 | 5 | 2.5 |
| Somewhat likely | 82 | 82 | 41.0 |
| Not very/Not at all likely | 111 + 2 | 113 | 56.5 |

### Reading it

- **Groups are defined by the operator**, in YAML, not by the model and not by index thresholds. Check `scenario.effective.json` to see which options were combined.
- **Groups can hide a bad distribution.** "Not very/Not at all" at 56.5% looks close to the human 50.5%, but it is 111 + 2 against the real 283 + 347. Always evaluate at the category level first; use groups for presentation.
- Group percentages do not sum to 100% if any option is ungrouped.

### Show it as

- A stacked bar (positive / undecided / negative) **under** the category chart, never instead of it.
- Name the groups exactly as configured; never relabel "Somewhat likely" as "undecided" unless the instrument says so.

---

## 6. `run.settings.json` — what produced the numbers

Not part of `report.json`, but required to interpret it. Two reports are comparable only when these match (except the field you are deliberately varying).

| Field | Meaning | Effect if different |
|---|---|---|
| `seed` | Sampling and per-respondent LLM seeds. | Different personas and different generations. |
| `prompt_version` | System-prompt revision (`trial-prompt-v3` currently). | Different instructions to the model. Results across versions are not comparable. |
| `persona_mode` | `attributes_only`: no traits or bios in the prompt. | — |
| `aggregation` | `unweighted`: each respondent counts 1. | — |
| `temperature` | `0.7`, fixed in code. | — |
| `settings.chat_model` | The model. | The main thing you are usually comparing. |
| `settings.openrouter_reasoning_effort` | Reasoning budget for models that support it. | Cost and possibly answers. Ignored by non-reasoning models. |
| `settings.openrouter_providers` | Who served the requests. | Same model on different hosts can differ slightly. |

Always print `chat_model`, `prompt_version`, `seed`, and `requested` next to any chart.

---

## 7. `responses.jsonl` — the raw data

One line per respondent, index order:

```json
{"index": 17, "persona_id": "p_00017", "status": "answered",
 "answer": {"option_index": 3,
            "reason": "I would rather stick with conventional meat…",
            "concern": "Safety of a new production method",
            "information_needed": "Long-term health studies",
            "change_condition": null}}
```

| Field | Meaning |
|---|---|
| `index`, `persona_id` | Join key to `personas.jsonl` for attributes. |
| `status` | `answered` or `technical_failure`. |
| `answer.option_index` | 0-based position in `scenario.options`. |
| `answer.reason` | Stated reason. May be `null`. |
| `answer.concern` | Main concern. `null` when none. |
| `answer.information_needed` | What would help them decide. `null` when none. |
| `answer.change_condition` | What could change their answer. `null` when none. |

`report.json` uses only `status`, `option_index`, and the first three `reason`s per option. Everything else is here for you to analyse:

- **Segment breakdowns** (not in the report): join on `index` with `personas.jsonl` and cross-tab `option_index` by any attribute (age group, region, party). With `requested = 200` most cells will be too small; use ≥ 1,000 for segment claims.
- **Null rates** for `concern` / `change_condition`: a model that fills every field every time is manufacturing content; a healthy run has a meaningful share of nulls.
- **Reason quality audit**: sample 30–50 at random and apply the checks in Section 4.

---

## 8. Evaluating against a human benchmark

Keep targets **outside** the inputs (never in the audience text, attributes, stimulus, or prompt). Freeze the inputs, run, then compare.

### Which percentage to compare

| Benchmark reports | Compare with |
|---|---|
| Percentages over all respondents, including don't-know | `percent_completed` |
| Percentages over substantive answers only | `percent_valid` |

AP-NORC FOOD7 publishes all-respondent weighted percentages, so use `percent_completed`.

### Example: FOOD7, Haiku, n = 200

| Response | AP-NORC (weighted) | This run | Δ (pp) |
|---|---:|---:|---:|
| Extremely likely | 6.75 | 0.0 | −6.8 |
| Very likely | 11.08 | 2.5 | −8.6 |
| Somewhat likely | 30.42 | 41.0 | +10.6 |
| Not very likely | 22.66 | 55.5 | **+32.8** |
| Not at all likely | 27.82 | 1.0 | **−26.8** |
| Nonresponse | 1.27 | 0.0 | −1.3 |
| Extremely/Very | 17.83 | 2.5 | −15.3 |
| Somewhat | 30.42 | 41.0 | +10.6 |
| Not very/Not at all | 50.48 | 56.5 | +6.0 |
| **Tail mass** (Extremely + Not at all) | **34.57** | **1.0** | **−33.6** |

### Is a gap real or noise?

Sampling error for a proportion $p$ at sample size $n$ is roughly

$$\pm\,1.96\sqrt{\frac{p(1-p)}{n}}$$

At $n = 200$ that is about ±3.5 pp near 30%, ±6.9 pp at $n = 50$, ±1.4 pp at $n = 1247$. Gaps of 27–33 pp are not sampling noise; they are the model's behaviour. Conversely, differences under ~4 pp at $n = 200$ are not evidence of anything.

The human study's own margin (±3.7 pp) applies to the human estimates, not to the synthetic ones. Do not transfer it.

### What to conclude from a gap

| Pattern | Likely cause | Next step |
|---|---|---|
| Endpoints empty, middle inflated | Model hedging / "measured" tuning | Try another model on the **same seed and n**; then prompt changes. |
| All mass on one side | Prompt or stimulus leading; or model's prior on the topic | Re-read the stimulus for added claims; check `as_of` is honoured. |
| Right shape, uniformly shifted | Population approximation (independent marginals, no weights) | Expected; report the gap, do not tune weights to fix it. |
| Nonresponse 0 vs a few percent | Forced-choice schema | Expected; note it. |
| Good groups, bad categories | Offsetting errors | Report at category level; do not claim agreement. |

### What a benchmark result does and does not mean

- Agreement on one question with one model is **not** validation of the product. It is one data point.
- Disagreement does **not** mean the pipeline is broken (check Section 9 first). It usually means the model or prompt does not behave like a population.
- The model may have seen the published study. A good match can be contamination rather than simulation. Prefer benchmarks published after the model's training cutoff when possible.

---

## 9. Run-quality checklist

Before interpreting any number:

1. `SUCCESS` exists and `technical_failures == 0`.
2. `requested` equals the intended `size`; category counts sum to `completed`.
3. `scenario_hash` matches any run you compare against.
4. `run.settings.json`: `chat_model`, `prompt_version`, `seed` are what you intended.
5. `scenario.effective.json`: labels are the exact instrument wording; groups are as intended.
6. `reason_examples` pass the Section 4 checks (first person, no invented facts, no placeholders).
7. Sample `responses.jsonl` for null rates and reason diversity.
8. Tail mass is non-trivial. A near-zero tail is a model problem, whatever the headline groups say.

---

## 10. Field quick reference

| Path | One-line meaning |
|---|---|
| `requested` | Personas sampled |
| `completed` | `requested − technical_failures` |
| `valid` | `completed − nonresponse` |
| `nonresponse` | Chose a nonresponse option |
| `technical_failures` | LLM calls failed; must be 0 |
| `categories[].count` | Respondents choosing this option |
| `categories[].percent_completed` | `count ÷ completed` |
| `categories[].percent_valid` | `count ÷ valid`; `null` for nonresponse |
| `categories[].reason_examples` | First 3 reasons, not top themes |
| `groups[].count` | Sum of member options |
| `groups[].percent_completed` | `count ÷ completed` |

---

## 11. Recommended report layout

1. **Instrument** — stimulus and question verbatim, `as_of` date, option labels.
2. **Sample** — `requested`, `completed`, `valid`, `technical_failures`; model, prompt version, seed.
3. **Distribution** — category bars with counts and `% completed`; benchmark alongside if available.
4. **Groups** — configured aggregates, named exactly as configured.
5. **Stated reasons** — audited examples per option, clearly marked as illustrative.
6. **Comparison with human data** (if any) — category-level table with Δ and the sampling-error note.
7. **Limits** — synthetic respondents; independent marginals; unweighted; forced choice; model/prompt version; not measured human demand.

### Example takeaway for this run

> On FOOD7 with 200 synthetic respondents, `claude-haiku` placed 2.5% in *Extremely/Very likely*, 41.0% in *Somewhat likely*, and 56.5% in *Not very/Not at all likely* (human: 17.8 / 30.4 / 50.5). The group totals look moderately close, but the category distribution does not: both endpoints are nearly empty (1.0% combined vs 34.6% in the human study) and 55.5% chose *Not very likely* (human 22.7%). The model hedges toward the middle rather than spreading like a population. Pipeline integrity is good (200/200, no failures); model behaviour is the limiting factor. Compare with another model on the same seed and n before changing the prompt.

---

## 12. Code references

| File | Role |
|---|---|
| [`sim/schemas.py`](../src/society/sim/schemas.py) | `TrialScenarioSpec`, `TrialOption`, `TrialAnswer`, `TrialRecord` |
| [`sim/prompts.py`](../src/society/sim/prompts.py) | `TRIAL_SYSTEM`, `trial_prompt`, `TRIAL_PROMPT_VERSION` |
| [`sim/engine.py`](../src/society/sim/engine.py) | `run_trial` — one call per persona, failures become records |
| [`report/metrics.py`](../src/society/report/metrics.py) | `summarize_trial` — counts, denominators, groups |
| [`report/schemas.py`](../src/society/report/schemas.py) | `TrialReport`, `TrialCount` |
| [`cli.py`](../src/society/cli.py) | `survey run` — artifacts, `SUCCESS` rule, `--retry-from` |
