# Cohuvo

- make install

Lab grown meat:

cohuvo population build --audience examples/audience.yaml --seed 42 --out out/personas.jsonl

cohuvo graph build --personas out/personas.jsonl --seed 42 --out-dir out/graph

cohuvo sim run --personas out/personas.jsonl --graph out/graph --scenario examples/scenario.yaml --seed 42 --out-dir out/sim

cohuvo report build --personas out/personas.jsonl --graph out/graph --sim out/sim --scenario examples/scenario.yaml --seed 42 --out-dir out/report

Netflix:

cohuvo population build \
  --audience examples/netflix-ads/audience.yaml \
  --seed 42 --out out/netflix-ads/personas.jsonl

cohuvo graph build \
  --personas out/netflix-ads/personas.jsonl \
  --seed 42 --out-dir out/netflix-ads/graph

cohuvo sim run \
  --personas out/netflix-ads/personas.jsonl \
  --graph out/netflix-ads/graph \
  --scenario examples/netflix-ads/scenario.yaml \
  --seed 42 --out-dir out/netflix-ads/sim

cohuvo report build \
  --personas out/netflix-ads/personas.jsonl \
  --graph out/netflix-ads/graph \
  --sim out/netflix-ads/sim \
  --scenario examples/netflix-ads/scenario.yaml \
  --seed 42 --out-dir out/netflix-ads/report


cohuvo survey run \
  --audience examples/surveys/biden-approval/audience.yaml \
  --scenario examples/surveys/biden-approval/scenario.yaml \
  --seed 42 \
  --out-dir out/surveys/biden-approval

### Recovering a failed survey

If a survey has technical failures, its diagnostic files are retained and no final
report is published. Retry only failed personas into a **new** directory:

```bash
cohuvo survey run \
  --audience examples/lam-meat/audience.yaml \
  --scenario examples/lam-meat/scenario.yaml \
  --seed 42 \
  --retry-from out/lab-grown-meat2 \
  --out-dir out/lab-grown-meat2-recovered
```

Keep the audience, scenario, seed, prompt version and settings identical to the
original run. Recovery validates the saved population and records, reuses successful
answers without API calls, and preserves original persona indices and request seeds.
It does not require the original response cache. The source directory is never modified.
Recovery currently requires a complete responses file containing one success or
technical-failure record per persona; interrupted, partially written runs are not supported.

Failed records now include a sanitized `failure_category`; older records without it
remain readable. Batch rejection logs include IDs and failure categories, never raw
respondent content. Empty or truncated outputs receive bounded regeneration retries
within the existing call timeout; refusals and permanent errors are not regenerated.

### Survey answer quality

`trial-prompt-v3` requests readable, option-consistent explanations without invented
personal histories or demographic stereotypes. All four optional explanation fields
allow JSON `null` but reject obvious corruption, placeholder-only strings and
punctuation-dominated fragments. Rejected outputs use the existing bounded
validation-retry/fallback path; unresolved items remain technical failures rather
than being replaced with invented answers. Invalid cached outputs are revalidated
by the OpenRouter client before reuse.

These are basic text-integrity checks, not semantic fact checking or a guarantee of
representative public opinion. Readable answers can still be inaccurate or biased.
Run the new prompt in a fresh output directory; recovery across prompt versions is
intentionally rejected to avoid mixing experiments.