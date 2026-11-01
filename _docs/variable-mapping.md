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

## Office-based events can be split by provider specialty (issue #5)

Checked directly in the 2022 office-based event file's SAS program statements
(`https://meps.ahrq.gov/data_stats/download_data/pufs/h239g/h239gsu.txt`, same variables present
in the 2023 file). Office-based visit records carry both the doctor's specialty and, for visits
to a non-doctor, the type of person seen.

| Variable | Label | Notes |
|---|---|---|
| `DRSPLTY_M18` | doctor's specialty | full specialty list: allergy/immunology, anesthesiology, cardiology, dermatology, endocrinology, family practice, gastroenterology, general practice, general surgery, geriatrics, gynecology/obstetrics, haematology, internal medicine, nephrology, neurology, oncology, ophthalmology, orthopedics, osteopathy, ENT, pathology, and more, `-1` when inapplicable (not a doctor visit) |
| `MEDPTYPE_M18` | type of medical person seen, when not a doctor | e.g. nurse practitioner, physician assistant |
| `VSTCTGRY` | best category for care received on the visit | general checkup, diagnosis or treatment, emergency, psychotherapy/mental health counselling, follow-up or post-operative, immunisations, vision exam, pregnancy-related, well-child exam, laser eye surgery, other |

This means the PMI-scope claim decision (decision gate 2) does not need a proxy for office-based
events, specialty and visit category are both directly available and can be used to decide which
office-based visits count as PMI-scope claims (e.g. specialist visits, excluding routine GP and
well-child checkups).

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
| Moderate/vigorous exercise 5x a week | `PHYEXE53` | confirmed present in both years, candidate lifestyle factor |

`DIABDX_M18` is identical in both years. Correction from an earlier version of this document,
which wrongly read `_M18` as an age-18+ restriction tag. AHRQ's own documentation defines the
`_Myy` suffix as marking the collection year in which a variable's definition or universe changed,
so `_M18` means "changed in collection year 2018", confirmed by web search against AHRQ's MEPS
documentation. The change itself is visible in the labels. Every other condition flag in this
list carries an explicit "(>17)" age restriction in its label (e.g. `CHDDXF` is valued `-1 =
INAPPLICABLE` for anyone outside that universe), but `DIABDX_M18`'s label is plain "DIABETES
DIAGNOSIS" with no age qualifier. That is consistent with 2018 being the year MEPS started asking
the diabetes diagnosis question of all ages rather than adults only. The `_M23`-style trap
`AGENTS.md` warns about (a suffix meaning "the question changed in 2023", not to be confused with
a `23` year suffix) did not apply to any variable in this shortlist, but the general `_Myy`
convention does, and was misread the first time.

### Smoking: two variables, different roles

| Role | Variable | Label | Use |
|---|---|---|---|
| Primary smoking factor | `OFTSMK53` | how often smoke cigarettes (>17), round 5/3, main interview (CAPI), all adults | rating factor |
| Consistency check only | `ADSMOK42` | SAQ: currently smoke, round 4/2, self-administered questionnaire | cross-check against `OFTSMK53`, not a rating factor |

`OFTSMK53` is the main-interview variable asked of all adults, so it has fuller coverage.
`ADSMOK42` comes from the self-administered questionnaire (SAQ), which a respondent can skip even
if they complete the main interview, so it has a coverage gap that `OFTSMK53` does not. M2 should
confirm the SAQ response rate for `ADSMOK42` before using it for anything beyond a consistency
check against `OFTSMK53`. `ADNSMK42` (advised to quit) is dropped from the shortlist, since it is
an SAQ follow-up with the same coverage gap and no rating-factor role of its own.

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
| Office-based expenditure, total | `OBVEXP22` | `OBVEXP23` |
| Office-based physician visits, count | `OBDRV22` | `OBDRV23` |
| Office-based physician expenditure | `OBDEXP22` | `OBDEXP23` |
| Outpatient facility + physician expenditure | `OPTEXP22` | `OPTEXP23` |
| ER facility + physician expenditure | `ERTEXP22` | `ERTEXP23` |
| Inpatient facility + physician expenditure | `IPTEXP22` | `IPTEXP23` |
| Prescription expenditure | `RXEXP22` | `RXEXP23` |

These service-category expenditure variables confirm the PMI-scope claim definition (decision gate
2, plan section 2.4) can be costed directly from the FYC file, `OBVEXP`/`IPTEXP`/`OPTEXP` give
office-based, inpatient and hospital-outpatient spend without needing to sum the event files for a
first-pass severity figure.

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

## Adult-only condition flags are coded -1 for children

`HIBPDX`, `CHDDX`, `ANGIDX`, `MIDX`, `OHRTDX`, `STRKDX`, `CHOLDX`, `CANCERDX` and `ARTHDX` all
carry an explicit "(>17)" age restriction in their label and format `-1 = INAPPLICABLE` for anyone
outside that universe (confirmed on `CHDDXF`, the same reserved-code pattern applies to the rest
of this group). `ASTHDX` and `DIABDX_M18` have no age restriction and so are valid at any age.

M2 needs an explicit coding rule for the `-1` values on the age-restricted flags, for example
whether a child is coded as "no diagnosis" (0) rather than left as a reserved negative code, and
how that interacts with the general reserved-code-to-null rule in plan section 2.2. This is not
decided here, it is a task for M2's validation layer.

## BMI: not available in the 2023 file

2022 has `ADBMI42` (adult BMI) and `CHBMIX42` (child BMI), both round 4/2. The 2023 file
(`h251su.txt`) has no BMI variable under any name or round suffix. This is not a round-labelling
artefact, the comparable-round smoking variable (`ADSMOK42`) exists fine in both years, so BMI
specifically was dropped from, or moved out of, the 2023 Full-Year Consolidated release.

**Decision:** BMI is excluded from the pooled 2022+2023 model and the final rating structure. The
main reason is that a factor absent from 2023 cannot be evaluated on the out-of-time test (plan
section 2.5), there is no 2023 BMI to check ranking, relativity stability or A/E against, so a
2022-only BMI relativity has no way to pass the validation design this project relies on. It would
also distort the pooled fit, since it is only present in half the pooled data.

A 2022-only BMI sensitivity analysis (showing the impact of a BMI rating factor alongside the
condition flags, the "full medical underwriting" story in plan section 2.4) is moved to the
stretch goals in plan section 5, not MVP, because it cannot be validated out-of-time.

Alternatives considered: checking a separate 2023 PUF (such as Preventive Care) for a BMI
variable, rejected for now because it adds another file to join for a factor not used in the
final rating structure anyway. Can be revisited if time allows.
