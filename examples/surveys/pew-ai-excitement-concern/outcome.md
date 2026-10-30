# Pew: Excitement and Concern About AI

## Verified Sources

- [Article](https://www.pewresearch.org/internet/2023/08/28/growing-public-concern-about-the-role-of-artificial-intelligence-in-daily-life/).
- [Questionnaire and topline](https://www.pewresearch.org/wp-content/uploads/2023/08/SR_23.08.28_views-of-ai_topline.pdf): page 1, `CNCEXC`, July 31-August 6, 2023 row.
- [Methodology](https://www.pewresearch.org/wp-content/uploads/2023/08/SR_23.08.28_views-of-ai_methodology.pdf): pages 1-2 for population, sample and dates.

**Human study:** ATP wave 132, 11,201 U.S. adults, July 31-August 6, 2023. Publication: August 28, 2023. The study used English/Spanish web interviews and survey weights. Synthetic size 200 is a diagnostic choice, not the human sample size.

## Instrument and Administration

[scenario.yaml](scenario.yaml) uses the source AI definition and CNCEXC question, with an ASCII ellipsis replacing the typographic ellipsis. All respondents were eligible.

The original definition precedes an awareness question (`AI_HEARD`) before CNCEXC. This standalone instrument omits that awareness question. The original randomized the first two options while keeping the third last; Cohuvo fixes the listed order. The topline's `No answer` is not an explicit offered option: the YAML's displayed `Prefer not to answer` is an approximation, not an exact replication of skipping.

## Comparison Table

Match report IDs and use `categories[].percent_completed`, retaining nonresponse in the denominator. Values are published rounded weighted percentages, not respondent counts. Use the 2023 row, not the different 2022 or 2021 distributions also printed in the topline.

| ID | Human label | Human % | GPT-OSS % | GPT delta (pp) | Haiku % | Haiku delta (pp) |
|---|---|---:|---:|---:|---:|---:|
| `more_excited` | More excited than concerned | 10 | | | | |
| `more_concerned` | More concerned than excited | 52 | | | | |
| `equally_concerned_excited` | Equally concerned and excited | 36 | | | | |
| `nonresponse` | No answer | 2 | | | | |

Each substantive option has its own identically named reporting group. These are emotional reactions, not a willingness-to-try score: do not equate excitement with adoption or concern with rejection.

## Audience Limitations

[audience.yaml](audience.yaml) includes only verified population eligibility, not demographic marginals or original respondents. All personas have identical attributes. Differences in answers arise from model generation seeds, not demographic variation. Generated internal traits are not shown to the survey model.

This is a **population-description-only diagnostic**, not a demographically matched benchmark. Do not import demographic weights from AP-NORC or another study as though they belonged to this sample. A closer audience needs documented targets or licensed microdata, and preserving joint profiles requires more than the current independent-attribute sampler.

## Evaluation

Require `SUCCESS`, zero technical failures, and consistent category counts. Compare both models using identical inputs, personas, prompt version, seed, and temperature. Delta is synthetic minus human percentage in percentage points. Half the sum of absolute category deltas gives total variation distance from this rounded reference.

Review whether a model defaults to the balanced option, invents personal AI use, adds post-fieldwork developments, or conflates concern with unwillingness to use AI. Do not force more extreme responses or tune inputs to these known percentages. Results from this public historical question may reflect training-data familiarity; a match does not establish accuracy on new customer concepts. Human margins of error do not apply to synthetic outputs.


#### Cohuvo outcome

Haiku

{"ts":"2026-10-30T17:44:39.893+00:00","level":"INFO","logger":"society.cli","msg":"token_usage_summary","stage":"survey","output":"out/surveys/pew-ai-excitement-concern/haiku","provider":"openrouter","chat_model":"anthropic/claude-haiku-5.5:batch","embedding_model":"qwen/qwen3-embedding-8b","accounting_scope":"observed_response_usage_this_invocation","chat_input_tokens":266600,"chat_output_tokens":28525,"embedding_input_tokens":0,"embedding_output_tokens":0,"total_input_tokens":266600,"total_output_tokens":28525,"chat_cache_hits":0,"embedding_cache_hits":0,"embedding_meter_available":true}

$0.0205

gpt

{"ts":"2026-10-30T17:56:09.072+00:00","level":"INFO","logger":"society.cli","msg":"token_usage_summary","stage":"survey","output":"out/surveys/pew-ai-excitement-concern/gpt","provider":"openrouter","chat_model":"openai/gpt-oss-120b:batch","embedding_model":"qwen/qwen3-embedding-8b","accounting_scope":"observed_response_usage_this_invocation","chat_input_tokens":112200,"chat_output_tokens":97041,"embedding_input_tokens":0,"embedding_output_tokens":0,"total_input_tokens":112200,"total_output_tokens":97041,"chat_cache_hits":0,"embedding_cache_hits":0,"embedding_meter_available":true}

$0.0165

