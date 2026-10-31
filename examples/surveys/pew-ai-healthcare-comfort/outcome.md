# Pew AI Healthcare Comfort: Documented Demographic Benchmark

## Purpose

A source-backed, age/sex-varied approximation for testing Cohuvo against Pew's AIHCCOMF results. Unlike the eligibility-only example, respondents have different visible demographic profiles. This is not a reconstruction of Pew's respondents or a validated human-demand estimator.

The scenario is identical to [the eligibility-only scenario](../pew-ai-healthcare-comfort/scenario.yaml). Changing only audience information permits a controlled diagnostic of whether documented demographic variation improves the output. Do not assume it will.

## Verified Sources

- [Pew study article](https://www.pewresearch.org/science/2023/02/22/60-of-americans-would-be-uncomfortable-with-provider-relying-on-ai-in-their-own-health-care/).
- [Pew questionnaire/topline](https://www.pewresearch.org/science/wp-content/uploads/sites/16/2023/02/PS_2023.02.22_AI-health_TOPLINE.pdf): PDF page 1, printed page 33, `AIHCCOMF`.
- [Pew methodology](https://www.pewresearch.org/science/2023/02/22/ai-health-methodology/).
- [Census Vintage 2022 national age/sex population CSV](https://www2.census.gov/programs-surveys/popest/datasets/2020-2022/national/asrh/nc-est2022-agesex-res.csv).

Pew interviewed **11,004 U.S. adults on December 12-18, 2022**; publication was February 22, 2023. Results use survey weights. The synthetic population of 200 is a diagnostic size, not the original human sample size. The scenario's `as_of` is the first fieldwork day, not the publication date.

## Audience Construction

Weights are derived from `POPESTIMATE2022` in the Census CSV. Use `SEX=1` for male and `SEX=2` for female; exclude the `SEX=0` combined-sex rows and `AGE=999` total rows. Sum adult single-year ages into four bands per sex. The oldest source category, `AGE=100`, is included in 65+.

| Joint category | Source ages | Population count used as relative weight |
|---|---|---:|
| Male, 18-29 | 18-29 | 27,371,398 |
| Male, 30-49 | 30-49 | 43,801,998 |
| Male, 50-64 | 50-64 | 31,106,544 |
| Male, 65+ | 65-100 source categories | 25,929,344 |
| Female, 18-29 | 18-29 | 26,149,897 |
| Female, 30-49 | 30-49 | 42,825,601 |
| Female, 50-64 | 50-64 | 31,786,440 |
| Female, 65+ | 65-100 source categories | 31,865,508 |
| **Total adults** | | **260,836,730** |

The sampler normalizes these counts into probabilities. Sampling one joint `age_and_sex` category preserves the age/sex relationship within this table; it avoids sampling age and sex independently. These are probabilities, not enforced quotas. A 200-person draw will not match the proportions exactly.

The source variable is **sex**, not an exhaustive gender-identity classification. Do not describe the two source categories as all possible gender identities. Traits generated internally by Cohuvo are not sent to the survey model.

### Remaining Population Differences

- Census annual resident-population estimates are not Pew's noninstitutionalized target universe: the Census counts include institutionalized residents. They also are not a December-specific population snapshot.
- This table is an external official population reference, not Pew's exact calibration targets or original respondent weights.
- Only age and sex vary. Education, race/ethnicity, region, health circumstances, AI experience, and other relevant characteristics are not reproduced. They are omitted rather than assigned invented proportions or histories.
- Cohuvo uses unweighted aggregation after sampling; the original probability-panel survey uses a more extensive weighting procedure.

Consequently, call this a **documented demographic approximation**, not an exact replication or fully representative sample. Recovering a closer audience requires appropriately licensed microdata or the complete documented weighting targets.

## Instrument

The stimulus and question follow AIHCCOMF verbatim apart from whitespace and using an ASCII ellipsis:

> Thinking about the use of artificial intelligence (AI) in health and medicine to do things like diagnose disease and recommend treatments...

> How would you feel if your health care provider relied on AI to do things like diagnose disease and recommend treatments for your medical care?

The original alternated the four substantive options forward or backward; this scenario uses a fixed forward order. Earlier questionnaire context and English/Spanish administration are not reproduced. `No answer` is an observed missing-response category in Pew, whereas the scenario displays `Prefer not to answer`. These differences remain even with a better demographic audience.

## Original Outcome and Comparison

Use `categories[].percent_completed`, matching stable IDs. Values are published rounded weighted percentages, not raw counts. Keep nonresponse in the denominator.

| ID | Human label | Human % | GPT-OSS % | GPT delta (pp) | Haiku % | Haiku delta (pp) |
|---|---|---:|---:|---:|---:|---:|
| `very_comfortable` | Very comfortable | 7 | | | | |
| `somewhat_comfortable` | Somewhat comfortable | 32 | | | | |
| `somewhat_uncomfortable` | Somewhat uncomfortable | 37 | | | | |
| `very_uncomfortable` | Very uncomfortable | 23 | | | | |
| `nonresponse` | No answer | 1 | | | | |

Configured groups, summed from rounded categories: **Comfortable 39%; Uncomfortable 60%; No answer 1%**. Groups can hide offsetting category errors, so always compare the complete distribution first.

Delta is synthetic minus human percentage, measured in percentage points. Half the sum of absolute category deltas gives total variation distance from this rounded reference. Smaller is closer on this instrument; it is not a universal model accuracy score.

## Running and Evaluating

Use the same model configurations as prior comparisons, with a new output directory for each run. These commands do not select a model: set `SOCIETY_CHAT_MODEL` appropriately in each terminal, and keep all other settings equal.

```bash
cohuvo survey run \
  --audience examples/surveys/pew-ai-healthcare-demographic-benchmark/audience.yaml \
  --scenario examples/surveys/pew-ai-healthcare-demographic-benchmark/scenario.yaml \
  --seed 42 \
  --out-dir out/comparison/pew-ai-healthcare-demographic-benchmark/gpt
```

For Haiku use the same inputs and seed, select the Haiku model, and change the output directory to `out/comparison/pew-ai-healthcare-demographic-benchmark/haiku`.

1. Require `SUCCESS`, zero technical failures, correct denominators, and category counts matching raw responses.
2. Verify identical effective inputs, sampled personas, prompt version, seed, and temperature between models. Preserve logs to compare actual cost and runtime.
3. Report the full category distribution and inspect results by age/sex, noting small subgroup sizes; do not make strong subgroup claims from tiny cells.
4. Audit invented medical diagnoses, treatment histories, unsupported safety guarantees, and whether reasons match the selected answer. Relying on AI to diagnose/recommend is not necessarily autonomous treatment without a clinician.
5. If testing the audience's contribution, compare with the eligibility-only version on the same instrument and model configuration. Preserve both outcomes, whether the added demographics help or hurt.
6. Freeze inputs before examining results. Do not adjust weights, inject attitudes, or force endpoint answers to match the targets. Confirm any promising configuration on held-out questions and repeated seeds.

Historical source familiarity can produce misleading agreement, and larger synthetic samples do not fix systematic model bias. Do not transfer Pew's human margin of error to these model-generated outputs. Published targets belong only in this outcome file, never in the respondent prompts.

#### Cohuvo outcome

| Response | Pew | GPT-OSS | Haiku |
|----------|----:|--------:|------:|
| Very comfortable | 7% | 0% | 0% |
| Somewhat comfortable | 32% | 63% | 1% |
| Somewhat uncomfortable | 37% | 37% | 99% |
| Very uncomfortable | 23% | 0% | 0% |
| No answer | 1% | 0% | 0% |

haiku

{"ts":"2026-10-30T18:29:27.498+00:00","level":"INFO","logger":"society.cli","msg":"token_usage_summary","stage":"survey","output":"out/surveys/pew-ai-healthcare-comfort/haiku","provider":"openrouter","chat_model":"anthropic/claude-haiku-5.5:batch","embedding_model":"qwen/qwen3-embedding-8b","accounting_scope":"observed_response_usage_this_invocation","chat_input_tokens":268555,"chat_output_tokens":26605,"embedding_input_tokens":0,"embedding_output_tokens":0,"total_input_tokens":268555,"total_output_tokens":26605,"chat_cache_hits":0,"embedding_cache_hits":0,"embedding_meter_available":true}

$0.0201

gpt

{"ts":"2026-10-31T00:08:24.359+00:00","level":"INFO","logger":"society.cli","msg":"token_usage_summary","stage":"survey","output":"out/survey/pew-ai-healthcare-comfort/gpt","provider":"openrouter","chat_model":"openai/gpt-oss-120b:batch","embedding_model":"qwen/qwen3-embedding-8b","accounting_scope":"observed_response_usage_this_invocation","chat_input_tokens":114955,"chat_output_tokens":73812,"embedding_input_tokens":0,"embedding_output_tokens":0,"total_input_tokens":114955,"total_output_tokens":73812,"chat_cache_hits":0,"embedding_cache_hits":0,"embedding_meter_available":true}

$0.0133
