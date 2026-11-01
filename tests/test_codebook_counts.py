# ruff: noqa: E501
"""Unweighted value counts of the key variables against the AHRQ codebook frequencies (issue #20).

EXPECTED holds the counts printed in the HC-243 (2022) and HC-251 (2023) codebooks, keyed by the
staged column name and then by value code. Age is in the codebook's own bands. The counts are
checked twice. Once against the codebook PDFs (so the table cannot drift from its source) and
once against the staged tables, which hold the values before any reserved-code treatment.
"""

from pathlib import Path

import duckdb
import pytest

from health_pricing.data.codebook import CodebookParseError, _parse_page, level_key, read_counts
from health_pricing.data.load import DUCKDB_PATH

REPO = Path(__file__).resolve().parents[1]
CODEBOOK_PDFS = {2022: REPO / "data/raw/h243cb.pdf", 2023: REPO / "data/raw/h251cb.pdf"}
YY = {2022: "22", 2023: "23"}
FLAGS = [
    "HIBPDX", "CHDDX", "ANGIDX", "MIDX", "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX",
    "ASTHDX", "DIABDX_M18",
]  # fmt: skip

EXPECTED = {
    2022: {
        "age": {"-1": 195, "0-4": 960, "5-17": 3367, "18-24": 1511, "25-44": 5308, "45-64": 5829, "65-85": 5261},
        "SEX": {"1": 10608, "2": 11823},
        "region": {"-1": 195, "1": 3443, "2": 4498, "3": 8602, "4": 5693},
        "RTHLTH31": {"-8": 24, "-7": 51, "-1": 472, "1": 5971, "2": 6971, "3": 6096, "4": 2260, "5": 586},
        "RTHLTH42": {"-8": 27, "-7": 56, "-1": 340, "1": 5608, "2": 7154, "3": 6567, "4": 2134, "5": 545},
        "RTHLTH53": {"-8": 32, "-7": 70, "-1": 256, "1": 5618, "2": 7216, "3": 6467, "4": 2205, "5": 567},
        "OFTSMK53": {"-8": 64, "-7": 170, "-1": 4551, "1": 1422, "2": 722, "3": 15502},
        "HIBPDX": {"-8": 43, "-7": 16, "-1": 4473, "1": 6788, "2": 11111},
        "CHDDX": {"-8": 35, "-7": 16, "-1": 4473, "1": 1099, "2": 16808},
        "ANGIDX": {"-8": 29, "-7": 18, "-1": 4473, "1": 386, "2": 17525},
        "MIDX": {"-8": 27, "-7": 16, "-1": 4473, "1": 747, "2": 17168},
        "OHRTDX": {"-8": 27, "-7": 16, "-1": 4473, "1": 2177, "2": 15738},
        "STRKDX": {"-8": 25, "-7": 18, "-1": 4473, "1": 888, "2": 17027},
        "CHOLDX": {"-8": 49, "-7": 17, "-1": 4473, "1": 6308, "2": 11584},
        "CANCERDX": {"-15": 2, "-8": 26, "-7": 16, "-1": 4473, "1": 2355, "2": 15559},
        "ARTHDX": {"-8": 33, "-7": 16, "-1": 4473, "1": 5303, "2": 12606},
        "ASTHDX": {"-8": 21, "-7": 20, "-1": 102, "1": 3098, "2": 19190},
        "DIABDX_M18": {"-8": 24, "-7": 20, "-1": 102, "1": 2544, "2": 19741},
    },
    2023: {
        "age": {"-1": 148, "0-4": 819, "5-17": 2829, "18-24": 1279, "25-44": 4481, "45-64": 4824, "65-85": 4539},
        "SEX": {"1": 9013, "2": 9906},
        "region": {"-1": 148, "1": 2894, "2": 3838, "3": 7377, "4": 4662},
        "RTHLTH31": {"-8": 21, "-7": 35, "-1": 334, "1": 5023, "2": 5788, "3": 5177, "4": 1973, "5": 568},
        "RTHLTH42": {"-8": 29, "-7": 34, "-1": 231, "1": 4772, "2": 6066, "3": 5435, "4": 1897, "5": 455},
        "RTHLTH53": {"-8": 14, "-7": 48, "-1": 212, "1": 4608, "2": 6159, "3": 5504, "4": 1905, "5": 469},
        "OFTSMK53": {"-8": 67, "-7": 103, "-1": 3833, "1": 1215, "2": 547, "3": 13154},
        "HIBPDX": {"-8": 29, "-7": 11, "-1": 3758, "1": 5667, "2": 9454},
        "CHDDX": {"-8": 22, "-7": 11, "-1": 3758, "1": 881, "2": 14247},
        "ANGIDX": {"-8": 22, "-7": 13, "-1": 3758, "1": 264, "2": 14862},
        "MIDX": {"-8": 17, "-7": 11, "-1": 3758, "1": 585, "2": 14548},
        "OHRTDX": {"-8": 20, "-7": 11, "-1": 3758, "1": 1833, "2": 13297},
        "STRKDX": {"-8": 17, "-7": 13, "-1": 3758, "1": 734, "2": 14397},
        "CHOLDX": {"-8": 41, "-7": 12, "-1": 3758, "1": 5363, "2": 9745},
        "CANCERDX": {"-15": 1, "-8": 22, "-7": 11, "-1": 3758, "1": 2084, "2": 13043},
        "ARTHDX": {"-8": 29, "-7": 11, "-1": 3758, "1": 4429, "2": 10692},
        "ASTHDX": {"-8": 19, "-7": 16, "-1": 82, "1": 2458, "2": 16344},
        "DIABDX_M18": {"-8": 18, "-7": 16, "-1": 82, "1": 2154, "2": 16649},
    },
}  # fmt: skip

AGE_BAND_SQL = (
    "CASE WHEN age = -1 THEN '-1' WHEN age BETWEEN 0 AND 4 THEN '0-4' "
    "WHEN age BETWEEN 5 AND 17 THEN '5-17' WHEN age BETWEEN 18 AND 24 THEN '18-24' "
    "WHEN age BETWEEN 25 AND 44 THEN '25-44' WHEN age BETWEEN 45 AND 64 THEN '45-64' "
    "WHEN age BETWEEN 65 AND 85 THEN '65-85' END"
)


def _differences(actual, expected):
    """Levels whose count differs, as {level: (actual, expected)}. Empty when they agree."""
    return {
        level: (actual.get(level), expected.get(level))
        for level in set(actual) | set(expected)
        if actual.get(level) != expected.get(level)
    }


def test_a_changed_or_missing_count_is_reported_as_a_difference():
    assert _differences({"1": 5, "2": 7}, {"1": 5, "2": 7}) == {}
    assert _differences({"1": 5, "2": 8}, {"1": 5, "2": 7}) == {"2": (8, 7)}
    assert _differences({"1": 5}, {"1": 5, "2": 7}) == {"2": (None, 7)}


def _codebook_name(year, column):
    return {"age": f"AGE{YY[year]}X", "region": f"REGION{YY[year]}"}.get(column, column)


def test_expected_table_covers_every_variable_the_issue_names_in_both_years():
    names = {"age", "SEX", "region", "RTHLTH31", "RTHLTH42", "RTHLTH53", "OFTSMK53", *FLAGS}
    for year in (2022, 2023):
        assert set(EXPECTED[year]) == names


def test_each_expected_variable_adds_up_to_the_persons_in_the_file():
    persons = {2022: 22_431, 2023: 18_919}
    for year, variables in EXPECTED.items():
        for column, counts in variables.items():
            assert sum(counts.values()) == persons[year], (year, column)


@pytest.mark.skipif(
    not all(p.exists() for p in CODEBOOK_PDFS.values()),
    reason="run `uv run python -m health_pricing.data.download` to fetch the codebooks",
)
@pytest.mark.parametrize("year", [2022, 2023])
def test_expected_counts_match_the_codebook_pdf(year):
    names = {column: _codebook_name(year, column) for column in EXPECTED[year]}
    printed = read_counts(CODEBOOK_PDFS[year], set(names.values()))
    for column, codebook_name in names.items():
        assert printed[codebook_name] == EXPECTED[year][column], (year, column)


def _staging_is_built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name IN ('stg_fyc_2022', 'stg_fyc_2023')"
        ).fetchone()
        return row[0] == 2
    finally:
        con.close()


@pytest.mark.skipif(not _staging_is_built(), reason="run the load script and dbt build")
@pytest.mark.parametrize("year", [2022, 2023])
def test_staged_counts_match_the_codebook(year):
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        for column, expected in EXPECTED[year].items():
            level = AGE_BAND_SQL if column == "age" else f"CAST({column} AS VARCHAR)"
            rows = con.execute(
                f"SELECT {level}, COUNT(*) FROM stg_fyc_{year} GROUP BY 1"
            ).fetchall()
            assert _differences(dict(rows), expected) == {}, (year, column)
    finally:
        con.close()


# --- The parser itself, on a hand-made page (lines come bottom to top, as pypdf returns them) ---

PAGE = """\
                    Total:         100                  5,000
    2 NO                                    60                  3,000
    1 YES                                   35                  1,900
    -8 DON'T KNOW                            5                    100
    Value                         Unweighted     Weighted by PERWT23F
End:                  2
Start:                1
Type:                 Num
Name:                 TESTVAR
"""


def test_parser_reads_a_block_and_checks_the_total():
    found = _parse_page(PAGE.splitlines(), {"TESTVAR"})
    assert found == {"TESTVAR": {"2": 60, "1": 35, "-8": 5}}


def test_parser_fails_loudly_when_counts_do_not_add_up():
    broken = PAGE.replace("35 ", "34 ")
    with pytest.raises(CodebookParseError):
        _parse_page(broken.splitlines(), {"TESTVAR"})


def test_level_key_reads_codes_and_age_bands():
    assert level_key("-1 INAPPLICABLE") == "-1"
    assert level_key("1 YES") == "1"
    assert level_key("0-4 AGE") == "0-4"
    assert level_key("65 - 85 AGE") == "65-85"
