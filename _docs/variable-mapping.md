# MEPS variable shortlist and 2022-23 mapping

Decision gate 1 (`AGENTS.md`). Decided 2026-10-31. This is the supporting evidence for the decision
logged in `_docs/decisions.md`. It exists so a reviewer can audit which MEPS variable feeds each
rating factor, frequency, severity or exposure field, and how its name changes between the 2022
(HC-243) and 2023 (HC-251) Full-Year Consolidated files.

## Method

Variable names and labels were taken directly from the SAS program statement files AHRQ publishes
alongside each PUF, not from an AI summary of the documentation PDF. These files are the actual
`INPUT`, `LABEL` and `FORMAT` statements used to build the dataset, so they are a primary source
for exact variable names.

- 2022: `https://meps.ahrq.gov/data_stats/download_data/pufs/h243/h243su.txt`
- 2023: `https://meps.ahrq.gov/data_stats/download_data/pufs/h251/h251su.txt`

An earlier pass summarised these files through an AI web-fetch tool and produced a wrong mapping
(it swapped the office-based and outpatient visit-count variables between the two years). That
summary was discarded. The tables below come from grepping the raw files directly.

## Confirmed companion event file identifiers

Needed for the scripted download in issue #4.

| File | 2022 | 2023 |
|---|---|---|
| Full-Year Consolidated | HC-243 | HC-251 |
| Office-based medical provider visits | HC-239G | HC-248G |
| Outpatient department visits | HC-239F | HC-248F |
| Hospital inpatient stays | HC-239D | HC-248D |

## Identical name in both years

| Role | Variable | Label |
|---|---|---|
| Household ID | `DUID` | panel + encrypted DU identifier |
| Person ID within household | `PID` | person number |
| Person ID | `DUPERSID` | `DUID` + `PID` |
| Panel | `PANEL` | panel number |
| Sex | `SEX` | sex |
| Variance stratum | `VARSTR` | variance estimation stratum |
| Variance PSU | `VARPSU` | variance estimation PSU |
| High blood pressure | `HIBPDX` | high blood pressure diagnosis (18+) |
| Coronary heart disease | `CHDDX` | coronary heart disease diagnosis (18+) |
| Angina | `ANGIDX` | angina diagnosis (18+) |
| Heart attack | `MIDX` | myocardial infarction diagnosis (18+) |
| Other heart disease | `OHRTDX` | other heart disease diagnosis (18+) |
| Stroke | `STRKDX` | stroke diagnosis (18+) |
| High cholesterol | `CHOLDX` | high cholesterol diagnosis (18+) |
| Cancer | `CANCERDX` | cancer diagnosis (18+) |
| Arthritis | `ARTHDX` | arthritis diagnosis (18+) |
| Asthma | `ASTHDX` | asthma diagnosis |
| Diabetes | `DIABDX_M18` | diabetes diagnosis |
| Currently smoke | `ADSMOK42` | SAQ: currently smoke |
| Advised to quit smoking | `ADNSMK42` | SAQ 12 months: doctor advised to quit |
| Smoking frequency | `OFTSMK53` | how often smoke cigarettes (18+) |

`DIABDX_M18` is identical in both years. The `_M18` is an age-18+ restriction tag on the variable,
not a "the question changed in 2023" marker. The trap `AGENTS.md` warns about (a `_M23`-style
suffix meaning a revised question) did not apply to any variable in this shortlist.

## Year-suffix mapping (22 to 23), same meaning

| Role | 2022 | 2023 |
|---|---|---|
| Age (edited/imputed, as of 31 Dec) | `AGE22X` | `AGE23X` |
| Census region (as of 31 Dec) | `REGION22` | `REGION23` |
| Health insurance coverage indicator | `INSCOV22` | `INSCOV23` |
| Family ID | `FAMID22` | `FAMID23` |
| Final person weight | `PERWT22F` | `PERWT23F` |
| Office-based provider visits, count | `OBTOTV22` | `OBTOTV23` |
| Outpatient dept. provider visits, count | `OPTOTV22` | `OPTOTV23` |
| Emergency room visits, count | `ERTOT22` | `ERTOT23` |
| Hospital discharges, count | `IPDIS22` | `IPDIS23` |
| Nights in hospital, discharges | `IPNGTD22` | `IPNGTD23` |
| Prescribed medicines incl. refills, count | `RXTOT22` | `RXTOT23` |
| Total health care expenditure | `TOTEXP22` | `TOTEXP23` |
| Paid by self/family | `TOTSLF22` | `TOTSLF23` |
| Paid by Medicare | `TOTMCR22` | `TOTMCR23` |
| Paid by Medicaid | `TOTMCD22` | `TOTMCD23` |
| Paid by private insurance | `TOTPRV22` | `TOTPRV23` |
| Paid by private insurance and TRICARE | `TOTPTR22` | `TOTPTR23` |

Before this check, `OBTOTV` (office-based) and `OPTOTV` (outpatient department) were easy to
confuse. Both exist in both years with these exact meanings, confirmed from the `LABEL` statements
(`"# OFFICE-BASED PROVIDER VISITS"` for `OBTOTV`, `"# OUTPATIENT DEPT PROVIDER VISITS"` for
`OPTOTV`).

## Round-based, not year-based

These follow a round-pair suffix (`31`, `42` or `53`, one per overlapping panel in that calendar
year) rather than a year suffix, and the pattern is the same in both years.

| Role | Pattern | Notes |
|---|---|---|
| Perceived health status | `RTHLTH31`, `RTHLTH42`, `RTHLTH53` | one value per round-pair, pick the latest round in scope or define a priority order in M2 |
| Perceived mental health | `MNHLTH31`, `MNHLTH42`, `MNHLTH53` | same pattern |
| Reference period start/end | `BEGRFM`/`BEGRFY`/`ENDRFM`/`ENDRFY` at `31`/`42`/`53`, plus a combined `22`/`23` version | the building block for the exposure (months in scope) offset |
| Eligible this round | `ELGRND31`/`ELGRND42`/`ELGRND53`, plus a combined `22`/`23` version | part-year eligibility |
| Asthma, still have | `ASSTIL31` | only one round-pair asks this question |

## BMI: not available in the 2023 file

2022 has `ADBMI42` (adult BMI) and `CHBMIX42` (child BMI), both round 4/2. The 2023 file
(`h251su.txt`) has no BMI variable under any name or round suffix. This is not a round-labelling
artefact, the comparable-round smoking variable (`ADSMOK42`) exists fine in both years, so BMI
specifically was dropped from, or moved out of, the 2023 Full-Year Consolidated release.

**Decision:** BMI is excluded from the pooled 2022+2023 model and the final rating structure.
`ADBMI42` is used only in a 2022-only sensitivity analysis, to show the impact of a BMI rating
factor alongside the condition flags (the "full medical underwriting" story in plan section 2.4).
A factor only present in half the pooled data would otherwise distort the pooled fit.

Alternatives considered: checking a separate 2023 PUF (such as Preventive Care) for a BMI
variable, rejected for now because it adds another file to join for a factor not used in the
final rating structure anyway. Can be revisited if time allows (see the stretch goals in plan
section 5).
