# Cohuvo — Product Overview

**Document date:** October 24, 2026  
**Product category:** AI-powered synthetic audience research  
**Operating model:** Human-operated, scenario-based research service

> **Implementation note**
>
> This overview describes the existing four-stage simulation workflow and the independent survey workflow discussed in the project conversation.
>
> The four-stage workflow was inspected in repository code. The survey workflow was provided as proposed code changes, which the project owner reported implementing. Those local changes and their test results have not been independently verified.
>
> This document is a product description, not a production-readiness or scientific-validation certification.

---

## 1. What Is Cohuvo?

Cohuvo helps users explore how a customer-defined audience might respond to an experience, product, or service using synthetic respondents.

Its core research goal is:

> Given a customer-defined audience and scenario, estimate how synthetic respondents distribute across willingness-to-try levels, explain their stated reasons, and identify concerns or conditions that may affect their responses.

Cohuvo currently has two distinct workflows:

1. **Four-stage purchase and social-influence simulation**
   - Builds a synthetic population.
   - Builds a social graph.
   - Simulates initial product exposure and subsequent influence rounds.
   - Produces purchase-oriented exploratory reports.

2. **Single-command independent survey**
   - Samples audience attributes.
   - Asks each synthetic respondent one configured question independently.
   - Reports response distributions and configured response groups.
   - Preserves respondent explanations without running a social simulation.

These workflows answer different questions. Their metrics must not be treated as interchangeable.

---

## 2. What Cohuvo Does—and Does Not—Measure

Cohuvo produces model-generated responses under configured assumptions.

It can help explore:

- Stated willingness to try a described offering.
- Differences across response categories.
- Reasons for interest, hesitation, or rejection.
- Potential concerns and information needs.
- Purchase-oriented reactions in the simulation workflow.
- How simulated attitudes evolve under configured social interactions and events.

It does not directly measure:

- Actual human participation.
- Real purchases or conversion rates.
- Observed willingness to pay.
- Actual word-of-mouth effects.
- Causal effects of advertising, peers, or pricing.
- A representative human population merely because its demographic proportions are approximated.

A synthetic result such as “40% selected a positive response” means:

> Under this run’s audience, scenario, model, and execution settings, 40% of the relevant synthetic responses fell into the configured positive categories.

It does not establish that 40% of the corresponding real population would behave that way.

---

## 3. Supported Workflows at a Glance

| Capability | Four-stage simulation | Independent survey |
|---|---|---|
| Primary purpose | Explore purchase reactions and social dynamics | Measure responses to one configured question |
| Customer research inputs | Audience YAML and simulation scenario YAML | Audience YAML and survey scenario YAML |
| Execution | Four sequential commands | One command |
| Population sampling | Yes | Yes |
| LLM-generated biographies | Enabled by default; optional | No |
| Injected behavioral traits used in prompts | Yes | No, in the proposed attributes-only path |
| Social graph | Required | Not used |
| Peer influence | Supported | Not used |
| Scenario events | Supported | Not supported |
| Multiple influence rounds | Supported | Not supported |
| Response scale | Existing purchase-oriented reaction schema | Configurable ordered options |
| Mandatory numeric price | Yes | No separate price field |
| Purchase-intent metrics | Yes | No |
| Pricing exploration | Yes | No |
| Category counts and percentages | Existing report focuses on adoption metrics | Yes |
| Configured response groups | Not the survey-style grouping mechanism | Yes |
| Automated segment reporting | Yes | Not included in the proposed survey report |
| Conditional follow-up questions | Not a generic questionnaire feature | Not included |
| Multi-select survey questions | Not a generic questionnaire feature | Not included |
| Final reports | JSON, Markdown, HTML | JSON, Markdown, basic HTML |

---

# Part I — Four-Stage Simulation

## 4. Purpose

The four-stage workflow is the original purchase-oriented simulation pipeline.

It explores questions such as:

- How do synthetic consumers initially react to a product and its price?
- How do their reactions change after hearing from peers?
- What objections emerge?
- Which audience segments show stronger simulated purchase intent?
- How do configured events coincide with changes in simulated reactions?
- What willingness-to-pay values do synthetic respondents state?

This workflow remains distinct from the revised willingness-to-try measurement.

### Important metric definition

In the inspected implementation:

> “Adoption” means the share of synthetic respondents whose `purchase_intent` is at least 4 on a 1–5 scale.

It does not mean:

- Actual adoption.
- Actual purchase.
- Willingness to try.
- Successful trial enrollment.

Customer-facing explanations must make that distinction explicit.

---

## 5. Four-Stage Inputs

### 5.1 Audience specification

The audience YAML defines:

- Audience description.
- Population size.
- Attribute distributions.
- Diversity setting.
- Non-buyer share.

Supported attribute specifications include:

- Numeric ranges.
- Categorical options.
- Relative categorical sampling weights.
- Single-select or multi-select categorical attributes.

For exclusive categories such as an age group or census region, use explicit categorical specifications with `pick: 1`.

Simple YAML list shorthand can produce multi-select attributes and should not be assumed to mean one category per respondent.

### 5.2 Simulation scenario specification

The simulation scenario uses fields such as:

- `name`
- `product`
- `pitch`
- `price`
- `rounds`
- `events`
- Peer-message and channel-post settings
- Broadcast and decay settings

The price contains:

- Numeric amount.
- Currency.
- Billing period.

An unspecified price is not supported by the original simulation schema.

**A price of zero means zero, not “price unknown.”**

---

## 6. Stage 1 — Build the Population

### Responsibility

Create synthetic personas from the audience specification.

The population includes:

- Persona identifiers and indices.
- Sampled attributes.
- Generated behavioral traits.
- Optional LLM-authored profiles.

Behavioral traits include:

- Openness.
- Price sensitivity.
- Skepticism.
- Social influence.
- Decision style.
- Prospect or non-buyer segment.

When enrichment is enabled, profiles add information such as:

- Name and location.
- Biography.
- Current solution.
- Switching trigger.

### Command

```bash
cohuvo population build \
  --audience examples/audience.yaml \
  --seed 42 \
  --out out/personas.json1
```

### Outputs

- `out/personas.json1`
- `out/personas.manifest.json`

The filename `personas.json1` intentionally uses the digit `1`. Its contents use JSONL-style records.

### Population limitation

Generated traits and biographies are modeling assumptions, not observed facts about real respondents.

The inspected enrichment prompt also imposed a US-suburban context. Unless corrected in the local implementation, that is a limitation for broader or non-US audiences.

---

## 7. Stage 2 — Build the Social Graph

### Responsibility

Create the network used for simulated communication and influence.

Graph construction uses persona information and graph configuration to establish relationships for subsequent simulation.

### Command

```bash
cohuvo graph build \
  --personas out/personas.json1 \
  --seed 42 \
  --out-dir out/graph
```

### Outputs

- Social graph artifacts.
- `graph.manifest.json`.

This stage is not itself an LLM-response stage.

### Interpretation

The graph represents a modeled network. It does not reconstruct the audience’s actual social relationships.

---

## 8. Stage 3 — Run the Simulation

### Responsibility

Expose personas to the offering and evolve reactions through configured rounds.

### Command

```bash
cohuvo sim run \
  --personas out/personas.json1 \
  --graph out/graph \
  --scenario examples/scenario.yaml \
  --seed 42 \
  --out-dir out/sim
```

### Execution behavior

- **Round 0:** every persona receives the initial exposure.
- **Later rounds:** personas may receive peer messages, channel posts, or scenario events.
- Routed personas may receive new LLM-generated reactions.
- Other personas may undergo code-driven decay.

The `rounds` setting counts influence rounds after initial exposure.

`rounds: 0` means exposure only, but it still uses the original purchase-oriented measurement.

### Response information

The original reaction schema includes:

- Interest.
- Purchase intent.
- Maximum stated price.
- Top objection.
- Whether the persona would share.
- Share message.
- Stance.
- Reasoning.

### Supported events

Examples include:

- Price changes.
- News.
- Competitor developments.
- Promotions.
- Outages.

### Outputs

- `events.jsonl`
- `checkpoint.json`
- `sim.manifest.json`

---

## 9. Stage 4 — Build the Simulation Report

### Responsibility

Aggregate the simulation outputs into structured and readable deliverables.

### Command

```bash
cohuvo report build \
  --personas out/personas.json1 \
  --graph out/graph \
  --sim out/sim \
  --scenario examples/scenario.yaml \
  --seed 42 \
  --out-dir out/report
```

### Report content

The existing report includes:

- Final and peak simulated adoption.
- Adoption over time.
- Segment-level purchase-intent metrics.
- Pricing and willingness-to-pay exploration.
- Objection themes.
- Simulated spread metrics.
- Event-associated changes.
- Selected synthetic respondent quotes.
- Optional LLM-generated narrative.

### Outputs

- `report.json`
- `report.md`
- `report.html`

The existing simulation HTML report is a self-contained offline report.

### Interpretation cautions

- A pricing curve is not a validated real-world demand curve.
- A revenue-oriented summary is not proof of an optimal price.
- Simulated influence attribution is not causal evidence.
- An interval computed from synthetic responses does not establish uncertainty about real human demand.

---

# Part II — Single-Command Independent Survey

## 10. Purpose

The survey workflow is designed for independent willingness-to-try measurement.

It answers:

> Given a defined audience and an exact question with explicit response options, how do synthetic respondents distribute across those options?

Unlike the simulation workflow, it does not model people hearing from one another or changing their answers over time.

It is suitable for:

- Standalone willingness-to-try questions.
- Exploratory concept-response distributions.
- Comparisons against compatible published survey questions.
- Research where exact response labels matter.

---

## 11. Survey Inputs

### 11.1 `audience.yaml`

Defines:

- Target audience description.
- Number of synthetic respondents.
- Attribute categories and distributions.

The proposed survey path uses the existing population sampler but passes only:

- Audience description.
- Sampled persona attributes.

It does not pass generated buyer traits or biographies into the survey prompt.

Although the sampler still creates trait fields internally, those fields do not determine the survey prompt in the proposed implementation.

### 11.2 Survey `scenario.yaml`

Defines:

- `schema_version`
- `name`
- `stimulus`
- `question`
- `options`
- Optional `as_of`

Each option can specify:

- Stable identifier.
- Display label.
- Optional reporting group.
- Whether it represents nonresponse.

### Price and other conditions

There is no mandatory structured price field.

Any price, eligibility requirement, time commitment, or obligation should be explicitly described in the stimulus when relevant.

The system must not infer:

- Unspecified price means free.
- Trying necessarily means buying.
- A trial requires switching providers.
- An offering has unstated safety guarantees or benefits.

For a study benchmark, retain the original question’s specificity and omissions rather than adding details that were not presented to its respondents.

---

## 12. Survey Execution

### Command

```bash
cohuvo survey run \
  --audience examples/audience.yaml \
  --scenario examples/survey_scenario.yaml \
  --seed 42 \
  --out-dir out/survey-001
```

The scenario may also be named `examples/scenario.yaml` if it contains the survey schema.

Separate filenames are useful when both workflows are used.

### No prerequisite stages

The survey command does not require running:

- `population build`
- `graph build`
- `sim run`
- `report build`

It performs its own population sampling, response collection, aggregation, and report generation.

### Internal sequence

1. Validate both YAML files.
2. Create a fresh output directory.
3. Save effective inputs and execution settings.
4. Sample audience attributes.
5. Build a bounded response schema from the configured options.
6. Ask each synthetic respondent the question independently.
7. Record answers and technical failures.
8. Calculate category counts and percentages.
9. Build diagnostic and final report artifacts.
10. Write `SUCCESS` after successful final artifact generation.

---

## 13. Survey Response Information

Each successful response contains:

- Selected option index.
- Optional stated reason.
- Optional concern.
- Optional information needed.
- Optional condition that could change the response.

Absent explanations or concerns may be `null`.

The system should not force every respondent to invent an objection or a condition for changing their mind.

### Option indices are not scores

An option index identifies a position in the configured list.

It is not automatically a 1–5 acceptance score.

For example, if “Extremely likely” appears first, it has a lower index than “Not at all likely.”

Acceptance groups must therefore use explicit configuration—not a hardcoded index threshold.

---

## 14. Survey Metrics and Denominators

The proposed report records:

| Metric | Meaning |
|---|---|
| `requested` | Number of synthetic respondents requested |
| `completed` | Number of successful structured responses, including nonresponse selections |
| `valid` | Number of substantive responses |
| `nonresponse` | Number selecting an option marked as nonresponse |
| `technical_failures` | Number of requests that failed through the handled LLM-error path |

Each category and configured group includes counts and percentages.

### Percentage of completed responses

`percent_completed` uses all successfully completed responses, including nonresponse selections, as its denominator.

### Percentage of valid responses

`percent_valid` uses only substantive answers.

Nonresponse categories do not receive a substantive-response percentage.

### Zero denominators

When the relevant denominator is zero, the percentage is `null`, not a fabricated zero.

### Group definitions

Groups depend on the instrument.

For Cohuvo’s proposed default willingness scale, positive responses could combine the two most favorable categories.

For a published benchmark, preserve its labels and grouping.

In particular:

> “Somewhat likely” must not automatically be relabeled “undecided.”

---

## 15. Survey Outputs

Under the proposed implementation, the output directory contains:

| File | Purpose |
|---|---|
| `audience.effective.json` | Parsed audience specification |
| `scenario.effective.json` | Parsed survey specification |
| `run.settings.json` | Execution settings with the API key excluded |
| `personas.json1` | Sampled persona records |
| `responses.jsonl` | Structured responses and handled technical failures |
| `run.summary.json` | Diagnostic aggregate summary |
| `report.json` | Final structured survey report |
| `report.md` | Readable survey report |
| `report.html` | Basic offline HTML rendering |
| `SUCCESS` | Completion marker written after final artifacts |

### Explanation reporting

The proposed report displays up to three available reason examples per category, selected in respondent order.

These are:

- Illustrative synthetic statements.
- Not ranked themes.
- Not representative quotes from real people.
- Not estimates of reason prevalence.

Complete response explanations remain available in `responses.jsonl`.

### HTML distinction

The survey HTML implementation is a basic escaped-text rendering.

It does not reuse the original simulation’s interactive dashboard or purchase-oriented sections.

---

## 16. Survey Performance and Failure Behavior

### Efficiency

The proposed survey executor:

- Creates at most the configured number of worker tasks.
- Builds the configured answer schema once per run.
- Reuses the existing LLM client.
- Leaves provider retries to the client.
- Aggregates results without LLM calls.
- Avoids graph construction, biographies, and embeddings.

Memory usage is O(N) because personas and responses are retained.

### Failure handling

Handled LLM errors are recorded as technical failures.

They are not converted into:

- Unwillingness.
- Low acceptance.
- Survey nonresponse.

If technical failures occur, the proposed command saves diagnostic outputs but withholds final reports and `SUCCESS`.

Unexpected exceptions or cancellation can interrupt the run before all diagnostics are written. Absence of `SUCCESS` means the output must not be treated as a completed deliverable.

---

## 17. Current Survey Scope Limits

The proposed survey workflow does not yet implement:

- Multiple questions in one instrument.
- Conditional follow-up questions.
- Randomized multi-select questions.
- Original respondent-level survey weights.
- Joint demographic sampling.
- Original interview-mode effects.
- Full bilingual survey administration.
- Automated segment-level report tables.
- Frequency-based clustering of reasons.
- Automatic scoring against external benchmark targets.

Listing these boundaries does not make them all launch requirements.

The immediate workflow is a single-question, independently answered synthetic survey.

---

# Part III — Benchmarking and Operation

## 18. Example: AP-NORC Cell-Based Meat Benchmark

The supplied February 2023 AP-NORC materials contain:

- FOOD7: likelihood of trying meat grown using animal cells.
- FOOD8: reasons for not eating it, asked only of respondents selecting either of the two least-likely FOOD7 categories.

### Supported benchmark scope

The current survey path can approximate standalone FOOD7 using:

- Original stimulus and question wording.
- Original substantive response labels.
- A documented demographic-marginal audience.
- An explicit historical-context date.
- Matching reporting groups.

### Not equivalent to full replication

The approximation does not reproduce:

- Original respondent identities or demographic correlations.
- The complete preceding questionnaire.
- The original web/telephone administration.
- The original voluntary nonresponse mechanism.
- The conditional randomized multi-select FOOD8 question.

Adding a visible nonresponse option preserves an output category but changes how nonresponse is elicited.

Generated free-text reasons are not interchangeable with FOOD8 checkbox responses.

### Keep targets separate

Published response percentages belong in the evaluation process, not in:

- The audience description.
- Persona attributes.
- Respondent-facing stimulus.
- The response-generation prompt.

Inputs should be frozen before examining benchmark agreement.

---

## 19. Audience Sampling and Representation

Categorical weights are relative probabilities used during sampling.

They are not:

- Exact population quotas.
- Individual respondent analysis weights.
- Proof of representativeness.

When published weighted demographic percentages are used as sampling weights, the generated audience approximates those marginal distributions in expectation.

Because attributes are sampled independently, real-world relationships between them are not preserved.

Increasing population size can reduce random sampling fluctuation within the model. It does not eliminate model bias or repair incorrect audience assumptions.

---

## 20. Configuration and Processing

The workflows use the existing provider-agnostic LLM interface.

The project includes support for:

- OpenRouter.
- Ollama.

Runtime settings use the `SOCIETY_` environment-variable prefix.

Relevant settings include:

- Provider and model.
- Concurrency.
- Timeouts.
- Retry limits.
- Token limits.
- Cache location.

### Hosted processing

With a hosted provider, prompt data leaves the local machine.

Customers should understand this before submitting confidential audience or scenario information.

### Reproducibility

Seeds support repeatable sampling and call-seed assignment.

They do not guarantee identical hosted-model responses across:

- Providers.
- Model revisions.
- Routing changes.
- Different execution dates.

Preserve the effective inputs, code version, settings, logs, and output artifacts for each run.

---

## 21. Command Names and Compatibility

The last inspected package configuration registered the `cohuvo` command.

Historical commands used `society`.

The `society` command is available only if the installed package retains that console-script alias.

The examples in this document use `cohuvo`.

### Scenario compatibility

The two scenario formats are different.

A survey scenario cannot be supplied unchanged to the original simulation command, and the old simulation scenario cannot be supplied unchanged to the survey command.

Maintain separate files when using both workflows.

---

## 22. Recommended Operating Procedure

Cohuvo is intended initially for human-operated research runs, not unattended multi-tenant SaaS execution.

For each customer or scenario:

1. Review the audience and scenario before execution.
2. Confirm the workflow measures the intended construct.
3. Use a separate output directory.
4. Preserve the original and effective inputs.
5. Record the actual executed code version.
6. Review logs and completion status.
7. Validate counts, percentages, and denominators.
8. Check narrative statements and synthetic quotes.
9. Explain assumptions and limitations in the deliverable.
10. Apply agreed retention and deletion procedures.

### Restart policy

For the survey path, use a fresh directory for each run.

For the original simulation, previously identified resume and manifest limitations remain relevant unless independently fixed.

The accepted operating workaround is to restart failed runs into fresh directories rather than rely on resume.

---

## 23. Product Positioning

Cohuvo is best positioned as:

> An AI-powered synthetic audience research tool for exploring stated willingness to try, understanding possible reasons and barriers, and testing hypotheses before or alongside human research.

The four-stage workflow adds:

> Exploratory purchase-oriented and social-influence simulation under explicit modeling assumptions.

The independent survey workflow adds:

> Configurable single-question measurement with explicit response distributions and denominators.

Neither workflow should be marketed as a replacement for demonstrated human validation.

---

## 24. Summary

Cohuvo supports two complementary but distinct capabilities:

### Four-stage simulation

**Population → Graph → Simulation → Report**

Use it to explore purchase-oriented responses, modeled peer influence, events, and pricing assumptions.

### Single-command survey

**Audience + Survey Scenario → Independent Responses → Distribution Report**

Use it to collect synthetic responses to a configured question without biographies, social influence, or purchase-intent substitution.

The central product principle is:

> Define the measurement explicitly, preserve its response categories, account for every respondent correctly, and distinguish synthetic exploratory findings from observed human behavior.
