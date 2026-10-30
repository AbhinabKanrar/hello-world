# Pew: Comfort With AI in Personal Health Care

## Verified Sources

- [Study article](https://www.pewresearch.org/science/2023/02/22/60-of-americans-would-be-uncomfortable-with-provider-relying-on-ai-in-their-own-health-care/).
- [Questionnaire and topline](https://www.pewresearch.org/science/wp-content/uploads/sites/16/2023/02/PS_2023.02.22_AI-health_TOPLINE.pdf): PDF page 1, printed page 33, `AIHCCOMF`.
- [Methodology](https://www.pewresearch.org/science/2023/02/22/ai-health-methodology/).
- [ATP wave 119 dataset page](https://www.pewresearch.org/dataset/american-trends-panel-wave-119/): microdata access was not verified or used.

**Human study:** 11,004 U.S. adults, December 12-18, 2022; publication February 22, 2023. ATP uses probability-based recruitment, English/Spanish web interviews, and survey weights. Synthetic size 200 is a diagnostic choice, not the original sample size.

## Instrument

The scenario preserves the AIHCCOMF introduction and question wording, with an ASCII ellipsis replacing the typographic ellipsis. All respondents were eligible. The original alternated option order 1-4 or 4-1; Cohuvo uses a fixed order. The instrument followed earlier questions, which this standalone approximation does not reproduce.

The topline's `No answer` is an observed missing-response category, not an offered response label. The YAML instead displays `Prefer not to answer`, an explicit administration difference; do not describe it as an exact replication.

## Comparison Table

Use `categories[].percent_completed`, matching IDs. These are rounded weighted human percentages, not counts.

| ID | Human label | Human % | GPT-OSS % | GPT delta (pp) | Haiku % | Haiku delta (pp) |
|---|---|---:|---:|---:|---:|---:|
| `very_comfortable` | Very comfortable | 7 | | | | |
| `somewhat_comfortable` | Somewhat comfortable | 32 | | | | |
| `somewhat_uncomfortable` | Somewhat uncomfortable | 37 | | | | |
| `very_uncomfortable` | Very uncomfortable | 23 | | | | |
| `nonresponse` | No answer | 1 | | | | |

Groups from the rounded categories: **Comfortable 39%; Uncomfortable 60%; No answer 1%**. Do not remove nonresponse from the denominator when comparing with these targets.

## Audience Limitations

[audience.yaml](audience.yaml) records only verified population eligibility. It does **not** reproduce the study's demographic distribution. No invented demographic weights or proxies from another study are used. All 200 respondents receive the same attributes; per-person generation seeds provide stochastic variation, not demographic diversity. Generated internal traits are not supplied to the survey model.

Use this as a **population-description-only model diagnostic**, not a demographically matched benchmark or representative audience. For the latter, obtain licensed microdata or documented population targets; the current independent-marginal sampler still cannot preserve joint respondent profiles.

## Evaluation

Require `SUCCESS`, zero technical failures, and counts summing to completed responses. Compare models on identical effective inputs, prompt version, seed, and temperature. Delta is synthetic minus human percentage in percentage points; half the sum of absolute category deltas summarizes total variation distance against this rounded reference.

Audit invented diagnoses, medical histories, guarantees, and answer-reason inconsistencies. A request to diagnose/recommend is not a request for autonomous treatment without a clinician. Preserve the wording rather than adding that assumption.

Keep targets out of inputs. Freeze configurations before viewing results, evaluate other held-out questions, and do not transfer the human survey's sampling error to synthetic output. This historical question may be known to the model; agreement alone does not establish human accuracy.