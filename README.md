# hello world

Synthetic audience research from an audience definition and a scenario. Outputs
are exploratory model-generated responses, not measured human demand.

| Workflow | Purpose | Execution |
|---|---|---|
| Independent survey | One question, configured response options, counts and stated reasons | `survey run` |
| Social simulation | Purchase intent, pricing and reactions across social-influence rounds | `study run`, or population -> graph -> simulation -> report individually |

## Setup

Requires Python 3.12+.

```bash
python3 -m venv venv
source venv/bin/activate
make install
```

Set `SOCIETY_OPENROUTER_API_KEY` in your shell before using OpenRouter. Never commit
credentials. All runtime settings use the `SOCIETY_` environment prefix; see
[src/society/config.py](src/society/config.py) for models, providers and defaults.

## Independent Survey

No population, graph or simulation commands are required first.

```bash
cohuvo survey run \
  --audience examples/surveys/pew-ai-healthcare-comfort/audience.yaml \
  --scenario examples/surveys/pew-ai-healthcare-comfort/scenario.yaml \
  --seed 42 \
  --out-dir out/surveys/pew-ai-healthcare-comfort/gpt
```

To specify a model, use this command

```bash
SOCIETY_CHAT_MODEL='anthropic/claude-haiku-5.5:batch' \
cohuvo survey run \
  --audience examples/surveys/pew-ai-healthcare-comfort/audience.yaml \
  --scenario examples/surveys/pew-ai-healthcare-comfort/scenario.yaml \
  --seed 42 \
  --out-dir out/surveys/pew-ai-healthcare-comfort/haiku
```


The scenario specifies a stimulus, question and response options. Results include
category/group counts, percentages with explicit denominators, and example reasons.
`responses.jsonl` retains the full answers and optional explanations.

A completed run writes `report.json` and `SUCCESS`. Handled technical failures
produce diagnostic `run.summary.json` instead; they are never counted as rejection
or survey nonresponse. Effective inputs, settings and sampled personas are saved
alongside the results.

## Social Simulation

The four stages can run as one command. This example uses MealMind, a priced
dinner-planning product.

```bash
cohuvo study run \
  --audience examples/simulation/mealmind-launch/audience.yaml \
  --scenario examples/simulation/mealmind-launch/scenario.yaml \
  --seed 42 --out-dir out/simulation/mealmind-study
```

`study run` executes population -> graph -> simulation -> report, recording stage
status in `study.json`. A failed stage is retried through its recovery path up to
`--stage-retries` times (default 2) per invocation; permanent errors such as
invalid inputs, authentication or insufficient credits stop immediately. Rerunning
the same command resumes from the failed stage, skipping completed ones. `SUCCESS`
is written only after the report exists. Inspect progress with
`cohuvo study status out/mealmind-study`.

On completion or failure the study logs a `token_usage_summary` covering every
attempt of every stage, including failed attempts and earlier invocations of the
same study. Per-stage usage is persisted in `study.json` and shown by `study status`.
Embedding tokens are reported only when the provider adapter meters them.

<details>
<summary>Running stages individually</summary>

Use the individual commands to reuse a population or graph across scenarios, or to
rebuild a report with different options.

```bash
cohuvo population build \
  --audience examples/simulation/mealmind-launch/audience.yaml \
  --seed 42 --out out/personas.jsonl

cohuvo graph build \
  --personas out/personas.jsonl \
  --seed 42 --out-dir out/graph

cohuvo sim run \
  --personas out/personas.jsonl --graph out/graph \
  --scenario examples/simulation/mealmind-launch/scenario.yaml \
  --seed 42 --out-dir out/sim

cohuvo report build \
  --personas out/personas.jsonl --graph out/graph --sim out/sim \
  --scenario examples/simulation/mealmind-launch/scenario.yaml \
  --seed 42 --out-dir out/report
```

</details>

Population building samples attributes/traits and optionally generates biographies.
Graph building creates the social network. Simulation exposes everyone in round 0,
then models reactions to messages and events. Reporting produces `report.json`.

Here, **adoption means purchase intent >= 4**, not actual purchases or willingness to
try. Survey and simulation scenarios have different schemas; do not interchange them.

## Examples

Each example directory contains its audience and scenario YAML files. Survey
reference results and approximation notes, where provided, belong in
`original-outcome.md`, never in respondent inputs.

| Example | Input Directory |
|---|---|
| MealMind simulation | [examples/simulation/mealmind-launch](examples/simulation/mealmind-launch) |
| Netflix simulation | [examples/simulation/netflix-ads](examples/simulation/netflix-ads) |
| Cell-grown meat survey | [examples/surveys/lab-meat](examples/surveys/lab-meat) |
| Other survey instruments | [examples/surveys](examples/surveys) |

## Recovery

Use `--retry-from` with a **fresh destination**, keeping inputs, seed, model, prompt
and non-secret settings unchanged. Recovery validates compatibility, reuses saved
successes without requiring the response cache, and leaves the source untouched.

| Stage | Retry Source | Work Reused |
|---|---|---|
| Survey | Failed survey directory | Successful answers; source must contain one record per persona |
| Population | Sidecar directory, e.g. `out/personas.recovery` | Successful profiles and deduplication-pass progress |
| Simulation | Failed simulation directory | Completed rounds and saved reactions from the incomplete round |

<details>
<summary>Recovery commands</summary>

**Survey**

```bash
cohuvo survey run \
  --audience examples/surveys/lab-meat/audience.yaml \
  --scenario examples/surveys/lab-meat/scenario.yaml \
  --seed 42 --retry-from out/survey \
  --out-dir out/survey-recovered
```

**Population**

```bash
cohuvo population build \
  --audience examples/simulation/mealmind-launch/audience.yaml \
  --seed 42 --retry-from out/personas.recovery \
  --out out/personas-recovered.jsonl
```

**Simulation**

```bash
cohuvo sim run \
  --personas out/personas.jsonl --graph out/graph \
  --scenario examples/simulation/mealmind-launch/scenario.yaml \
  --seed 42 --retry-from out/sim \
  --out-dir out/sim-recovered
```

After population recovery, build the graph using the recovered population. After
simulation recovery, build the report with `--sim out/sim-recovered` and the same
population and graph.

</details>

Population and simulation require the new `progress.sqlite` journal; older failed
runs without it are unsupported. Their journals support local interruptions and
commit completed simulation rounds atomically. Survey recovery does not support
partially written response files. Never resume by rerunning into an existing output
directory. Preserve recovery files privately: they contain generated research data.

Stage token summaries describe the current invocation, not the combined cost of
all attempts. Simulation statistics retain the complete round history.

## Models and Batch Requests

Select a model per command or terminal with `SOCIETY_CHAT_MODEL`. For a controlled
comparison, keep the same effective inputs, seed, temperature and prompt version;
use separate output directories and verify the saved scenario before interpreting
results. A seed makes population sampling repeatable, not hosted inference perfectly
deterministic.

Batch routing is controlled by `SOCIETY_OPENROUTER_BATCH_ENABLED` and
`SOCIETY_OPENROUTER_BATCH_MIN_REQUESTS`. Batch requests are chunked by count and byte
budgets; smaller workloads use synchronous calls. Providers must support the chosen
model and request mode. Batch completion can take substantially longer than sync.

**Stopping the CLI does not cancel a submitted batch.** Recovery does not reattach
to live server-side batches. Results not received and saved locally may still incur
charges, and another attempt can resubmit that work. Check credits and running batches
before restarting. Customer inputs are sent to the configured model provider.

## Quality and Development

Inputs and responses use typed validation with bounded correction retries. Survey
explanation fields permit JSON `null` and reject obvious corruption/placeholders.
These are structural/text checks, not semantic fact checking: readable answers can
still invent facts, stereotype respondents or misrepresent population distributions.
Review outputs before delivery; benchmark agreement on one question is not validation.

```bash
make lint
make type
make test
```

Use `cohuvo --help` or `<command> --help` for available options.

## Further Reading

- [docs/cohuvo-product-guide.md](docs/cohuvo-product-guide.md)
- [docs/reading-survey-report-json.md](docs/reading-survey-report-json.md)
- [docs/reading-report-json.md](docs/reading-report-json.md)