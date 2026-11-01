"""Verify the reserved-code claims in _docs/variable-mapping.md against the raw AHRQ files.

Three QA rounds caught prose claims in that document that were wrong for some subset of
variables (a swapped pair, a variable present in only one year, a blanket claim false for
derived variables, a variable with year-dependent codes, variables missing from both tables
entirely). This test replaces the prose with an executable table, checked directly against both
years' SAS program statement files, so a future edit that drifts from reality fails a test
instead of waiting for a fourth QA round.

Needs data/raw/h243su.txt and data/raw/h251su.txt, which health_pricing.data.load.fetch_layout
downloads as a side effect of running the loader. Skips if absent, same as test_load.py.
"""

from pathlib import Path

import pytest

from health_pricing.data.sas_layout import extract_value_block, parse_layout, parse_reserved_codes

H243SU = Path("data/raw/h243su.txt")
H251SU = Path("data/raw/h251su.txt")

pytestmark = pytest.mark.skipif(
    not (H243SU.exists() and H251SU.exists()),
    reason="data/raw/h243su.txt or h251su.txt not downloaded, run the load script",
)

ALL_FOUR = {"-15", "-8", "-7", "-1"}

# (variable, year, expected reserved codes). Mirrors the two tables in
# "Reserved negative codes and age top-coding" in _docs/variable-mapping.md exactly.
EXPECTED_CODES = [
    # Carries the convention, all four codes
    ("SEX", 2022, ALL_FOUR),
    ("SEX", 2023, ALL_FOUR),
    ("OFTSMK53", 2022, ALL_FOUR),
    ("OFTSMK53", 2023, ALL_FOUR),
    ("PHYEXE53", 2022, ALL_FOUR),
    ("PHYEXE53", 2023, ALL_FOUR),
    ("ASTHDX", 2022, ALL_FOUR),
    ("ASTHDX", 2023, ALL_FOUR),
    ("DIABDX_M18", 2022, ALL_FOUR),
    ("DIABDX_M18", 2023, ALL_FOUR),
    ("ADSMOK42", 2023, ALL_FOUR),
    ("ADBMI42", 2022, ALL_FOUR),
    ("ASSTIL31", 2022, ALL_FOUR),
    ("ASSTIL31", 2023, ALL_FOUR),
    # PID: year-dependent, the headline finding of QA round 3
    ("PID", 2022, ALL_FOUR),
    ("PID", 2023, set()),
    # -1 only
    ("AGE22X", 2022, {"-1"}),
    ("AGE23X", 2023, {"-1"}),
    ("REGION22", 2022, {"-1"}),
    ("REGION23", 2023, {"-1"}),
    ("INSCOV22", 2022, {"-1"}),
    ("INSCOV23", 2023, {"-1"}),
    # Partial exception
    ("CHBMIX42", 2022, {"-15", "-1"}),
    # No codes at all (continuous or fully-imputed, never negative)
    ("TOTEXP22", 2022, set()),
    ("TOTEXP23", 2023, set()),
    ("PERWT22F", 2022, set()),
    ("PERWT23F", 2023, set()),
    ("VARSTR", 2022, set()),
    ("VARSTR", 2023, set()),
    ("VARPSU", 2022, set()),
    ("VARPSU", 2023, set()),
    ("DUID", 2022, set()),
    ("DUID", 2023, set()),
    ("DUPERSID", 2022, set()),
    ("DUPERSID", 2023, set()),
    ("PANEL", 2022, set()),
    ("PANEL", 2023, set()),
]

# QA round 4 found the hand-written list above was itself a sample, the same "checked a few,
# generalised to the group" mistake the prose had, just moved into the test. These groups are
# generated, not hand-picked, so adding a round number or a new condition flag later can't be
# silently skipped. Every entry was independently verified against both raw files before being
# turned into a generator (see the session log), not derived from the document's own prose.

# All nine adult-only condition flags, both years, all four codes.
CONDITION_FLAGS = [
    "HIBPDX", "CHDDX", "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX",
]  # fmt: skip
for _var in CONDITION_FLAGS:
    EXPECTED_CODES += [(_var, 2022, ALL_FOUR), (_var, 2023, ALL_FOUR)]

# Perceived health/mental health, all three round-pairs, both years, all four codes.
for _var in ["RTHLTH", "MNHLTH"]:
    for _round in ["31", "42", "53"]:
        EXPECTED_CODES += [(f"{_var}{_round}", 2022, ALL_FOUR), (f"{_var}{_round}", 2023, ALL_FOUR)]

# Utilisation counts that carry -15 ("cannot be computed") only, in their own year. The
# cross-year entry is empty because the year-suffixed variable does not exist in the other year.
for _var in ["OBTOTV", "OPTOTV", "ERTOT", "IPDIS", "OBDRV"]:
    EXPECTED_CODES += [
        (f"{_var}22", 2022, {"-15"}),
        (f"{_var}22", 2023, set()),
        (f"{_var}23", 2022, set()),
        (f"{_var}23", 2023, {"-15"}),
    ]

# Exposure building blocks. Round-pair forms (31/42/53) are identical in structure across both
# years, confirmed, so they get ALL_FOUR in both years. Combined-year forms (22/23) are
# year-specific like OBTOTV22/23 above, each only exists in its own year's file, so the
# cross-year entry is empty, not ALL_FOUR (this exact mistake was caught by this same test on
# the first attempt at this expansion, see the session log).
for _var in ["BEGRFM", "BEGRFY", "ENDRFM", "ENDRFY"]:
    for _round in ["31", "42", "53"]:
        EXPECTED_CODES += [(f"{_var}{_round}", 2022, ALL_FOUR), (f"{_var}{_round}", 2023, ALL_FOUR)]
for _round in ["31", "42", "53"]:
    EXPECTED_CODES += [(f"ELGRND{_round}", 2022, ALL_FOUR), (f"ELGRND{_round}", 2023, ALL_FOUR)]
for _var in ["ENDRFM", "ENDRFY", "ELGRND"]:
    EXPECTED_CODES += [
        (f"{_var}22", 2022, ALL_FOUR),
        (f"{_var}22", 2023, set()),
        (f"{_var}23", 2022, set()),
        (f"{_var}23", 2023, ALL_FOUR),
    ]

# Dollar-total variables, no reserved codes at all, both years.
for _var in [
    "TOTSLF", "TOTMCR", "TOTMCD", "TOTPRV", "TOTPTR",
    "OBVEXP", "OBDEXP", "OPTEXP", "ERTEXP", "IPTEXP", "RXEXP",
]:  # fmt: skip
    EXPECTED_CODES += [(f"{_var}22", 2022, set()), (f"{_var}23", 2023, set())]

# Counts with no reserved codes at all, both years (unlike OBTOTV/OPTOTV/ERTOT/IPDIS/OBDRV above).
for _var in ["IPNGTD", "RXTOT"]:
    EXPECTED_CODES += [(f"{_var}22", 2022, set()), (f"{_var}23", 2023, set())]


@pytest.fixture(scope="module")
def codes_by_year():
    return {2022: parse_reserved_codes(H243SU), 2023: parse_reserved_codes(H251SU)}


@pytest.fixture(scope="module")
def names_by_year():
    return {
        2022: {f.name for f in parse_layout(H243SU)},
        2023: {f.name for f in parse_layout(H251SU)},
    }


@pytest.mark.parametrize("variable,year,expected", EXPECTED_CODES)
def test_reserved_codes_match_variable_mapping_doc(codes_by_year, variable, year, expected):
    actual = codes_by_year[year].get(variable, set())
    assert actual == expected


def test_no_combined_year_version_of_begrfm_begrfy(names_by_year):
    # "Reference period start" row's key claim, corrected from an earlier version of the doc
    # that wrongly said a combined-year BEGRFM22/23 and BEGRFY22/23 existed. parse_reserved_codes
    # alone can't tell "doesn't exist" apart from "exists with no codes", so this checks
    # existence directly via the INPUT block instead.
    for var in ["BEGRFM22", "BEGRFY22"]:
        assert var not in names_by_year[2022], f"{var} unexpectedly exists in 2022"
    for var in ["BEGRFM23", "BEGRFY23"]:
        assert var not in names_by_year[2023], f"{var} unexpectedly exists in 2023"


@pytest.mark.parametrize("su_path,variable", [(H243SU, "AGE22X"), (H251SU, "AGE23X")])
def test_age_top_coding_at_85(su_path, variable):
    # Scoped to this variable's own VALUE block (QA round 4: a whole-file substring match would
    # still pass even if this specific variable's own top-coding line were wrong, since the same
    # "65 - 85 = ..." text also appears in other age-like variables' blocks in the same file).
    block = extract_value_block(su_path, variable)
    assert block, f"{variable} has no VALUE block in {su_path}"
    assert '65 - 85 = "65-85 AGE"' in block
