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

from health_pricing.data.sas_layout import parse_reserved_codes

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
    ("RTHLTH31", 2023, ALL_FOUR),
    ("MNHLTH31", 2023, ALL_FOUR),
    ("OFTSMK53", 2022, ALL_FOUR),
    ("OFTSMK53", 2023, ALL_FOUR),
    ("PHYEXE53", 2022, ALL_FOUR),
    ("PHYEXE53", 2023, ALL_FOUR),
    ("HIBPDX", 2022, ALL_FOUR),
    ("CHDDX", 2023, ALL_FOUR),
    ("ASTHDX", 2022, ALL_FOUR),
    ("ASTHDX", 2023, ALL_FOUR),
    ("DIABDX_M18", 2022, ALL_FOUR),
    ("DIABDX_M18", 2023, ALL_FOUR),
    ("ADSMOK42", 2023, ALL_FOUR),
    ("ADBMI42", 2022, ALL_FOUR),
    ("BEGRFM31", 2022, ALL_FOUR),
    ("BEGRFM31", 2023, ALL_FOUR),
    ("ENDRFM22", 2022, ALL_FOUR),
    ("ENDRFM23", 2023, ALL_FOUR),
    ("ELGRND22", 2022, ALL_FOUR),
    ("ELGRND23", 2023, ALL_FOUR),
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
    # -15 only
    ("OBTOTV22", 2022, {"-15"}),
    ("OBTOTV23", 2023, {"-15"}),
    ("OPTOTV22", 2022, {"-15"}),
    ("ERTOT23", 2023, {"-15"}),
    ("IPDIS22", 2022, {"-15"}),
    ("OBDRV23", 2023, {"-15"}),
    # Partial exception
    ("CHBMIX42", 2022, {"-15", "-1"}),
    # No codes at all (continuous or fully-imputed, never negative)
    ("TOTEXP22", 2022, set()),
    ("TOTEXP23", 2023, set()),
    ("TOTSLF23", 2023, set()),
    ("TOTMCR23", 2023, set()),
    ("TOTMCD23", 2023, set()),
    ("TOTPRV23", 2023, set()),
    ("TOTPTR23", 2023, set()),
    ("OBVEXP23", 2023, set()),
    ("OBDEXP23", 2023, set()),
    ("OPTEXP23", 2023, set()),
    ("ERTEXP23", 2023, set()),
    ("IPTEXP23", 2023, set()),
    ("RXEXP23", 2023, set()),
    ("PERWT22F", 2022, set()),
    ("PERWT23F", 2023, set()),
    ("IPNGTD22", 2022, set()),
    ("IPNGTD23", 2023, set()),
    ("RXTOT22", 2022, set()),
    ("RXTOT23", 2023, set()),
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


@pytest.fixture(scope="module")
def codes_by_year():
    return {2022: parse_reserved_codes(H243SU), 2023: parse_reserved_codes(H251SU)}


@pytest.mark.parametrize("variable,year,expected", EXPECTED_CODES)
def test_reserved_codes_match_variable_mapping_doc(codes_by_year, variable, year, expected):
    actual = codes_by_year[year].get(variable, set())
    assert actual == expected


def test_age_top_coding_at_85(codes_by_year):
    for su_path, var in [(H243SU, "AGE22X"), (H251SU, "AGE23X")]:
        text = Path(su_path).read_text(encoding="latin-1")
        assert '65 - 85 = "65-85 AGE"' in text, f"{var} top-coding at 85 not found in {su_path}"
