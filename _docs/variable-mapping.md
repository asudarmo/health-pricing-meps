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
events. Specialty and visit category are both directly available and can be used to decide which
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

### Smoking: two variables, different roles, and different year availability

| Role | Variable | Label | Years available | Use |
|---|---|---|---|---|
| Primary smoking factor | `OFTSMK53` | how often smoke cigarettes (>17), round 5/3, main interview (CAPI), all adults | 2022 and 2023, confirmed by grepping both raw files directly | rating factor |
| Consistency check only, 2023 only | `ADSMOK42` | SAQ: currently smoke, round 4/2, self-administered questionnaire | **2023 only** | cross-check against `OFTSMK53` in 2023, not usable in 2022 or the pooled model |

Correction from an earlier version of this document, caught at QA, which claimed `ADSMOK42` was
identical in both years. It is not. It does not exist anywhere in `h243su.txt` (2022), only in
`h251su.txt` (2023). This is the same class of error the office-based/outpatient swap was (a
2022/2023 availability mix-up), caught this time by QA rather than the user, which is why the
acceptance criteria for this issue now explicitly require checking presence in both years for
every listed variable, not just mapping the name. `OFTSMK53` is the main-interview variable asked
of all adults in both years, so it is used as the rating factor. `ADSMOK42` can only support a
2023-only consistency check, not a pooled one. `ADNSMK42` (advised to quit) is dropped from the
shortlist, because it is an SAQ follow-up with the same 2023-only availability and no
rating-factor role of its own.

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

## Reserved negative codes and age top-coding

Added at QA, which flagged that the acceptance criterion "reserved negative codes and top-coding
confirmed for each variable" was only checked for the adult-only condition flags, not the rest of
the shortlist. A first attempt at this section claimed the reserved-code convention applied to
"every numeric variable in this shortlist". A second QA re-check found this false. `TOTEXP23`
and `PERWT23F` carry no negative codes at all, confirmed directly in their `VALUE` statements.
The corrected version below checks every shortlisted variable individually rather than asserting
blanket coverage. An unchecked generalisation across the full shortlist is the same mistake the
office-based/outpatient swap and the `ADSMOK42` error both were.

Checked directly in both years' `VALUE` statements for every variable in this shortlist, two
groups exist.

**Carry the reserved-code convention** (`-1` inapplicable, `-7` refused, `-8` don't know, `-15`
cannot be computed, from `AGENTS.md` section 2.2), because they come directly from a survey
question that can go unanswered or not apply:

| Variables | Codes present |
|---|---|
| `SEX`, `RTHLTH31/42/53`, `MNHLTH31/42/53`, `OFTSMK53`, `PHYEXE53` | all four (`-15`, `-8`, `-7`, `-1`) |
| `AGE22X`/`AGE23X`, `REGION22`/`23`, `INSCOV22`/`23` | `-1` only |
| `OBTOTV`, `OPTOTV`, `ERTOT`, `IPDIS`, `OBDRV` (both years) | `-15` only, for counts that cannot be derived |
| The adult-only condition flags (`HIBPDX` etc.) | all four, confirmed on `CHDDXF`, with `-1`'s age-restriction meaning documented separately above |
| `BEGRFM`/`BEGRFY` (round-pair only), `ENDRFM`/`ENDRFY`/`ELGRND` (round-pair and combined-year forms), `ASSTIL31` | all four |
| `ASTHDX`, `DIABDX_M18` (both years) | all four, same pattern as the age-restricted condition flags, confirmed directly even though these two have no age restriction |
| `ADSMOK42` (2023 only, see the smoking section above) | all four |
| `ADBMI42` (2022 only, excluded from the model, see the BMI section below) | all four |
| `CHBMIX42` (2022 only, child BMI, excluded from the model) | `-15` and `-1` only, not the full set unlike `ADBMI42`, confirmed on `CHBMIX42F` |

A third-round correction: `PID` does not belong in the no-codes group below for both years.
`PIDF` in 2022 carries the full reserved-code set before its `101-503 = VALID ID` range, but
`PIDF` in 2023 has no reserved codes at all, only `101-401 = VALID ID`. This difference is
genuinely year-dependent and was confirmed directly on both files, not assumed from one year.
`DUID`, `DUPERSID` and `PANEL` are ID-range-only in both years.

**Carry no reserved codes**, because they are continuous or fully-imputed derived quantities that
are never negative, confirmed directly, not assumed:

| Variables | Why |
|---|---|
| `TOTEXP`, `TOTSLF`, `TOTMCR`, `TOTMCD`, `TOTPRV`, `TOTPTR` (both years) | imputed dollar totals, `VALUE TOTEXP23F` etc. start at `0`, no negative codes |
| `OBVEXP`, `OBDEXP`, `OPTEXP`, `ERTEXP`, `IPTEXP`, `RXEXP` (both years) | same, service-category dollar totals |
| `PERWT22F`/`PERWT23F` | survey weight, `VALUE PERWT23FF` starts at `0`, no negative codes |
| `IPNGTD`, `RXTOT` (both years) | counts, but unlike `OBTOTV`/`OPTOTV`/`ERTOT`/`IPDIS`/`OBDRV` these specifically do not carry `-15` either, confirmed by the same check |
| `VARSTR`, `VARPSU` | survey-design variables, confirmed no `VALUE` statement includes a negative code, never missing by construction |
| `DUID`, `DUPERSID`, `PANEL` | identifiers, confirmed valid-ID ranges only, no reserved codes. `PID` is excluded from this row, see above |
| `FAMID22`/`23` | not the standard numeric convention, uses its own character code `'0' = "NON-RESPONSE"` instead, confirmed on `$FAMID23F` |

M2's validation layer needs this distinction, a rule that nulls out `-1`/`-7`/`-8`/`-15` on every
numeric column would silently corrupt `TOTEXP23` or `PERWT23F` if those values ever legitimately
appeared (they are at or above zero by construction, so this is a low-risk but real trap).

Age top-coding: confirmed directly in both years' `VALUE` statements. `AGE22XF` and `AGE23XF`
both group the stored value as `65 - 85 = "65-85 AGE"`, meaning the underlying `AGE22X`/`AGE23X`
value itself is capped at 85, anyone older is recorded as exactly 85, not that 65-85 is a single
coded category. M2's validation layer needs to treat 85 as a top-coded ceiling, not a literal age,
when using age as a continuous rating factor or computing age-related derived fields.

## Round-based, not year-based

These follow a round-pair suffix (`31`, `42` or `53`, one per overlapping panel in that calendar
year) rather than a year suffix, and the pattern is the same in both years.

| Role | Pattern | Notes |
|---|---|---|
| Perceived health status | `RTHLTH31`, `RTHLTH42`, `RTHLTH53` | one value per round-pair, pick the latest round in scope or define a priority order in M2 |
| Perceived mental health | `MNHLTH31`, `MNHLTH42`, `MNHLTH53` | same pattern |
| Reference period start | `BEGRFM31`/`BEGRFM42`/`BEGRFM53`, `BEGRFY31`/`BEGRFY42`/`BEGRFY53` | round-pair only, confirmed no combined `22`/`23` version exists for the start date, corrected from an earlier version of this document that wrongly claimed one did |
| Reference period end | `ENDRFM31`/`42`/`53`, `ENDRFY31`/`42`/`53`, plus a combined `ENDRFM22`/`23` and `ENDRFY22`/`23` | the end date gets a combined-year version but the start date does not, and this asymmetry is the building block for the exposure (months in scope) offset |
| Eligible this round | `ELGRND31`/`42`/`53`, plus a combined `ELGRND22`/`23` | part-year eligibility |
| Asthma, still have | `ASSTIL31` | only one round-pair asks this question |

## Adult-only condition flags are coded -1 for children

`HIBPDX`, `CHDDX`, `ANGIDX`, `MIDX`, `OHRTDX`, `STRKDX`, `CHOLDX`, `CANCERDX` and `ARTHDX` all
carry an explicit "(>17)" age restriction in their label and format `-1 = INAPPLICABLE` for anyone
outside that universe (confirmed on `CHDDXF`, the same reserved-code pattern applies to the rest
of this group). `ASTHDX` and `DIABDX_M18` have no age restriction and so are valid at any age.

M2 needs an explicit coding rule for the `-1` values on the age-restricted flags, for example
whether a child is coded as "no diagnosis" (0) rather than left as a reserved negative code, and
how that interacts with the general reserved-code-to-null rule in plan section 2.2. This is not
decided here. It is a task for M2's validation layer.

## BMI: not available in the 2023 file

2022 has `ADBMI42` (adult BMI) and `CHBMIX42` (child BMI), both round 4/2. The 2023 file
(`h251su.txt`) has no BMI variable under any name or round suffix.

**Decision:** BMI is excluded from the pooled 2022+2023 model and the final rating structure. The
main reason is that a factor absent from 2023 cannot be evaluated on the out-of-time test (plan
section 2.5). There is no 2023 BMI to check ranking, relativity stability or A/E against, so a
2022-only BMI relativity has no way to pass the validation design this project relies on. It would
also distort the pooled fit, since it is only present in half the pooled data.

A 2022-only BMI sensitivity analysis (showing the impact of a BMI rating factor alongside the
condition flags, the "full medical underwriting" story in plan section 2.4) is moved to the
stretch goals in plan section 5, not MVP, because it cannot be validated out-of-time.

Alternatives considered: checking a separate 2023 PUF (such as Preventive Care) for a BMI
variable, rejected for now because it adds another file to join for a factor not used in the
final rating structure anyway. Can be revisited if time allows.
