# EU Sport Frequency: Original Results and Comparison Sheet

## Source

**Study:** Special Eurobarometer 574, Sport and physical activity, wave 105.3.

- [Official survey page](https://europa.eu/eurobarometer/surveys/detail/3685).
- [Full report](Sport%20and%20physical%20activity_SP574_report_en.pdf): page 6 for methodology; pages 11 and 14 for QB1R results; TS1-TS2 for sampling and country populations.
- [Summary](Sport%20and%20physical%20activity_SP574_summary_en.pdf): page 8 for frequency results.
- [Infographic](Sport%20and%20physical%20activity_SP574_infographics_en.pdf): page 1 for the four substantive percentages.

The report states **26,508 human respondents** and overall fieldwork of **9 April-4 May 2026**. The target covers EU Member State nationals aged 15+ resident in the EU27, with Cyprus limited to the government-controlled area. Interviews used national languages. EU estimates use survey weights, including adjustments for countries' 15+ population shares.

The country table lists some starts earlier than the stated overall period. The scenario uses 9 April as the report-level date convention, not as every respondent's interview date.

## Question and Definition

**Reported variable: QB1R.**

> How often do you exercise or play sport?

The report defines exercise as:

> By "exercise" we mean any form of physical activity which you do in a sport context or sport-related setting, such as swimming, training in a fitness centre or a sport club, brisk walking or running (e.g. in the park)

The supplied PDFs establish the reported categories below. They do not establish the original interview options or any recoding behind QB1R. The Cohuvo scenario is therefore a **report-category approximation**, not an exact questionnaire replication. Displaying "Don't know" explicitly is also an approximation to the unverified original administration.

## Category Comparison

Compare the human percentages with `categories[].percent_completed`, matching on `id`, not row position. All model columns below are intentionally blank until runs finish.

| YAML / report ID | Published category | Human EU27 % | GPT-OSS % | GPT delta (pp) | Haiku % | Haiku delta (pp) |
|---|---|---:|---:|---:|---:|---:|
| `almost_daily` | Almost daily | 9 | | | | |
| `several_times_a_week` | Several times a week | 38 | | | | |
| `seldom` | Seldom | 14 | | | | |
| `never` | Never | 39 | | | | |
| `nonresponse` | Don't know | 0 | | | | |
| **Total** | | **100** | | | | |

These are **rounded weighted percentages**, not raw human counts. Published 0% does not necessarily mean zero respondents. Do not infer exact counts from these values, force synthetic counts to match, or treat rounding as exact precision.

## Group Comparison

These totals sum the published rounded categories and match the configured groups in [scenario.yaml](scenario.yaml).

| Configured group | Member IDs | Human reference % | GPT-OSS % | Haiku % |
|---|---|---:|---:|---:|
| At least several times a week | `almost_daily` + `several_times_a_week` | 47 | | |
| Seldom / Never | `seldom` + `never` | 53 | | |

Nonresponse belongs to neither group. Compare groups using `groups[].percent_completed`, but always inspect category-level results first: offsetting category errors can make a group look accurate.

## How to Tally a Run

1. Require `SUCCESS`, `technical_failures == 0`, and the intended `requested` count. Check that category counts sum to `completed`.
2. Record the model, prompt version, seed, scenario hash, and effective audience. Verify that both model runs use identical sampled personas and instruments.
3. Enter each category's `percent_completed` above. Percentages are already on a 0-100 scale; do not multiply them by 100 again.
4. Compute each delta as **synthetic percentage minus human percentage**. Positive means overestimation; negative means underestimation. The unit is percentage points (pp).
5. Summarize distribution discrepancy as **half the sum of absolute category deltas** across all five options. This is total variation distance expressed in percentage points; smaller is closer to this rounded reference, not a general accuracy score.
6. Audit individual reasons for invented exercise routines, demographic stereotypes, unsupported health assumptions, and answer-reason inconsistencies.

For example, a synthetic "Never" result of 50% has a delta of **+11 pp** against 39%. This example is illustrative, not an observed model result.

Use `percent_completed`, not `percent_valid`, for this comparison so an explicit synthetic nonresponse is retained. The published 0% nonresponse is rounded; full denominator and recoding details still require the original questionnaire/results documentation.

## Interpretation Limits

- A 200-person synthetic run is not the original 26,508-person probability sample and is not required to reproduce exact counts.
- Country weights in [audience.yaml](audience.yaml) come from TS2 population totals. Other demographic weights remain unverified user assumptions, sampled independently of country and each other.
- A 200-person random draw may omit smaller countries. It does not enforce quotas or reproduce the original joint demographics and respondent analysis weights.
- English-only generation does not reproduce national-language interviews or interview-mode effects.
- This question concerns reported behaviour, not willingness to try. Demographic attributes do not establish an individual's actual exercise history.
- A match on this question is one comparison, not scientific validation or evidence of equivalent human responses. Do not transfer human survey margins of error to synthetic output.
- Keep this document and all target percentages outside respondent prompts, audience attributes, and scenario content. Freeze inputs before examining results; do not tune them merely to match the targets.

Venue, motivation, walking, and non-sport physical-activity results are separate measures and are not benchmark targets for this scenario.


#### Cohuvo outcome

Haiku outout

{"ts":"2026-10-30T15:10:54.647+00:00","level":"INFO","logger":"society.cli","msg":"token_usage_summary","stage":"survey","output":"out/surveys/eu-sport-activity/haiku","provider":"openrouter","chat_model":"anthropic/claude-haiku-5.5:batch","embedding_model":"qwen/qwen3-embedding-8b","accounting_scope":"observed_response_usage_this_invocation","chat_input_tokens":281015,"chat_output_tokens":22791,"embedding_input_tokens":0,"embedding_output_tokens":0,"total_input_tokens":281015,"total_output_tokens":22791,"chat_cache_hits":0,"embedding_cache_hits":0,"embedding_meter_available":true}

$0.0197

gpt output

{"ts":"2026-10-30T16:31:05.333+00:00","level":"INFO","logger":"society.cli","msg":"token_usage_summary","stage":"survey","output":"out/surveys/eu-sport-activity/gpt","provider":"openrouter","chat_model":"openai/gpt-oss-120b:batch","embedding_model":"qwen/qwen3-embedding-8b","accounting_scope":"observed_response_usage_this_invocation","chat_input_tokens":123934,"chat_output_tokens":74989,"embedding_input_tokens":0,"embedding_output_tokens":0,"total_input_tokens":123934,"total_output_tokens":74989,"chat_cache_hits":0,"embedding_cache_hits":0,"embedding_meter_available":true}

$0.0139
