"""Reconciliation of the data layer to AHRQ's published figures (issue #19).

tests/data/published_figures.csv holds each published figure with its source and location. The
tests compare it with the loaded and staged data, and (when the PDFs are downloaded) with the
codebooks it was taken from. Weights are used here for sanity checks only.
"""

import csv
from pathlib import Path

import duckdb
import pytest

from health_pricing.data.codebook import read_counts
from health_pricing.data.load import DUCKDB_PATH

REPO = Path(__file__).resolve().parents[1]
FIGURES = REPO / "tests" / "data" / "published_figures.csv"
CODEBOOKS = {2022: REPO / "data/raw/h243cb.pdf", 2023: REPO / "data/raw/h251cb.pdf"}
YY = {2022: "22", 2023: "23"}


def published(measure, year, level=""):
    with open(FIGURES, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["measure"] == measure and int(row["year"]) == year and row["level"] == level:
                return int(row["value"])
    raise KeyError((measure, year, level))


def bands(year):
    with open(FIGURES, encoding="utf-8", newline="") as handle:
        return sorted(
            {
                row["level"]
                for row in csv.DictReader(handle)
                if row["measure"] == "totexp_band_weighted_persons" and int(row["year"]) == year
            }
        )


def test_every_published_figure_has_a_source_and_location():
    with open(FIGURES, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        assert row["source"] and row["location"].startswith("https://meps.ahrq.gov/"), row


def test_the_mean_for_2023_is_not_in_the_table_because_no_published_figure_was_found():
    # Recorded openly. See _docs/reconciliation.md. Adding the figure here switches the check on.
    with pytest.raises(KeyError):
        published("mean_totexp_per_person", 2023)


def _built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name IN ('stg_fyc_2022', 'stg_fyc_2023', 'mart_person_year')"
        ).fetchone()
        return row[0] == 3
    finally:
        con.close()


built = pytest.mark.skipif(not _built(), reason="run the load script and dbt build")


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    yield connection
    connection.close()


@built
@pytest.mark.parametrize("year", [2022, 2023])
def test_person_counts_match_the_documentation_exactly(con, year):
    on_file = con.execute(f"SELECT COUNT(*) FROM raw.fyc_{year}").fetchone()[0]
    positive = con.execute(f"SELECT COUNT(*) FROM stg_fyc_{year} WHERE perwt > 0").fetchone()[0]
    in_mart = con.execute(
        "SELECT COUNT(*) FROM mart_person_year WHERE year = ?", [year]
    ).fetchone()[0]
    assert on_file == published("persons_on_file", year)
    assert positive == published("persons_positive_weight", year) == in_mart


@built
@pytest.mark.parametrize("year", [2022, 2023])
def test_weighted_population_matches_the_codebook_total(con, year):
    total = con.execute(f"SELECT SUM(perwt) FROM stg_fyc_{year}").fetchone()[0]
    assert round(total) == published("weighted_population", year)
    in_mart = con.execute(
        "SELECT SUM(perwt) FROM mart_person_year WHERE year = ?", [year]
    ).fetchone()[0]
    assert in_mart == pytest.approx(total, rel=1e-12)  # zero-weight people add nothing


@built
def test_weighted_mean_total_expenditure_matches_the_published_2022_mean(con):
    mean = con.execute("SELECT SUM(TOTEXP * perwt) / SUM(perwt) FROM stg_fyc_2022").fetchone()[0]
    assert round(mean) == published("mean_totexp_per_person", 2022)  # $6,765, to the dollar
    in_mart = con.execute(
        "SELECT SUM(m.perwt * p.TOTEXP) / SUM(m.perwt) FROM mart_person_year m "
        "JOIN int_person_clean p USING (year, DUPERSID) WHERE m.year = 2022"
    ).fetchone()[0]
    assert in_mart == pytest.approx(mean, rel=1e-12)


def _band_sql(level):
    low, _, high = level.partition("-")
    return f"TOTEXP BETWEEN {low} AND {high}" if high else f"TOTEXP = {low}"


@built
@pytest.mark.parametrize("year", [2022, 2023])
def test_persons_and_weighted_persons_by_expenditure_band_match_the_codebook(con, year):
    # The codebook prints the persons in each TOTEXP band, unweighted and weighted. This checks the
    # weighted expenditure distribution for 2023 too, where no published mean was found.
    assert len(bands(year)) == 5
    for level in bands(year):
        count, weighted = con.execute(
            f"SELECT COUNT(*), SUM(perwt) FROM stg_fyc_{year} WHERE {_band_sql(level)}"
        ).fetchone()
        assert count == published("totexp_band_unweighted_persons", year, level), (year, level)
        assert round(weighted) == published("totexp_band_weighted_persons", year, level)


@pytest.mark.skipif(
    not all(p.exists() for p in CODEBOOKS.values()), reason="download the codebooks first"
)
@pytest.mark.parametrize("year", [2022, 2023])
def test_the_published_table_matches_the_codebook_pdf(year):
    name = f"TOTEXP{YY[year]}"
    unweighted = read_counts(CODEBOOKS[year], {name})[name]
    weighted = read_counts(CODEBOOKS[year], {name}, weighted=True)[name]
    for level, value in unweighted.items():
        assert published("totexp_band_unweighted_persons", year, level) == value
    for level, value in weighted.items():
        assert published("totexp_band_weighted_persons", year, level) == value
