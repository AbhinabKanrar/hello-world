# Pew: Willingness to Ride in a Driverless Passenger Vehicle

## Verified Sources

- [Study article](https://www.pewresearch.org/internet/2022/03/17/americans-cautious-about-the-deployment-of-driverless-cars/).
- [Questionnaire and topline](https://www.pewresearch.org/wp-content/uploads/sites/20/2022/03/PI_2022.03.17_ai-he-TOPLINE.pdf): PDF page 14 (printed 147), `DCCARSVIG`; PDF page 15 (printed 148), `DCARS3`.
- [Methodology](https://www.pewresearch.org/internet/2022/03/17/ai-human-enhancement-methodology/).
- [ATP wave 99 dataset page](https://www.pewresearch.org/dataset/american-trends-panel-wave-99/): microdata access was not verified or used.

**Human study:** November 1-7, 2021; publication March 17, 2022. The full ATP wave had 10,260 respondents, but **DCARS3 was asked only of Form 1, n = 5,153**. Do not use the full wave size as the question denominator. Respondents were U.S. adults, interviewed online in English/Spanish; published estimates use survey weights.

## Instrument and Administration

The YAML preserves the `DCCARSVIG` definition and the `DCARS3` question with its four substantive response labels. It does not add a price, free ride, safety guarantee, purchase commitment, or requirement to replace a personal car.

The original driverless block was one of three randomized blocks on Form 1. Within it, `DCARS1` asked about prior awareness and `DCARS2` asked about societal benefit before `DCARS3`. This standalone approximation omits those questions and broader questionnaire context. The supplied DCARS3 topline does not specify response-order randomization; no such claim is made here.

The source reports `No answer`; Cohuvo instead displays `Prefer not to answer`. Displayed nonresponse is not equivalent to original skipping. This is a standalone instrument approximation, not a full replication.

## Comparison Table

Use `categories[].percent_completed`, matching IDs. These are the published rounded weighted percentages over Form 1 respondents, not counts.

| ID | Human label | Human % | GPT-OSS % | GPT delta (pp) | Haiku % | Haiku delta (pp) |
|---|---|---:|---:|---:|---:|---:|
| `definitely_want` | Definitely want | 14 | | | | |
| `probably_want` | Probably want | 23 | | | | |
| `probably_not_want` | Probably NOT want | 32 | | | | |
| `definitely_not_want` | Definitely NOT want | 30 | | | | |
| `nonresponse` | No answer | 1 | | | | |

Groups summed from the rounded topline categories: **Want to ride 37%; Do not want to ride 62%; No answer 1%**.

**Rounding distinction:** the article describes 63% as not wanting to ride, while the two rounded negative category percentages sum to 62%. Preserve both source values: use 32% and 30% for category comparisons and 62% as their arithmetic sum, not as a claimed unrounded group estimate. Do not alter category targets merely to force agreement with the article headline.

## Audience Limitations

Synthetic size 200 is a diagnostic choice. [audience.yaml](audience.yaml) defines only population eligibility: every persona has the same country and age-eligibility attributes, without original demographic proportions or joint profiles. Per-person generation seeds are not demographic diversity, and internal generated traits are excluded from survey prompts.

This is a **population-description-only baseline**. For a demographically matched study, obtain licensed Form 1 microdata or documented weighted demographic targets. Do not independently sample prior enthusiasm, existing willingness to ride, or the published answer percentages into personas to manufacture a match.

## Evaluation

Require `SUCCESS`, zero technical failures, and counts summing to completed responses. Compare models on identical frozen inputs, prompt version, seed, and temperature. Delta is synthetic minus human percentage in percentage points; half the sum of absolute category deltas summarizes total variation distance against the rounded five-category reference.

Audit endpoint suppression, invented ride experiences, assumed safety guarantees, and confusion between riding once and purchasing a vehicle. Report costs and failures separately from survey answers. Historical source familiarity can inflate agreement; this one comparison does not validate customer-demand forecasts. Do not transfer human sampling margins of error to synthetic output.