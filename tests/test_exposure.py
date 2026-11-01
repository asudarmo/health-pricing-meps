"""Tests for the exposure derivation in int_person_exposure (issue #13).

The model SQL runs on a throwaway dbt project whose int_person_clean holds hand-made persons, one
per case, so the months can be checked by hand. Needs dbt and the dbt_utils-free model only.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

REPO = Path(__file__).resolve().parents[1]
MODEL = REPO / "dbt" / "models" / "intermediate" / "int_person_exposure.sql"

COLUMNS = [
    "year", "DUPERSID",
    *(f"{stem}{rnd}" for rnd in (31, 42, 53)
      for stem in ("ELGRND", "BEGRFM", "BEGRFY", "ENDRFM", "ENDRFY")),
]  # fmt: skip


def person(year, name, rounds):
    """rounds maps 31, 42 or 53 to (eligible, begin month, begin year, end month, end year)."""
    row = {"year": year, "DUPERSID": name}
    for rnd in (31, 42, 53):
        elg, bm, by, em, ey = rounds.get(rnd, (3, -1, -1, -1, -1))
        row.update({
            f"ELGRND{rnd}": elg, f"BEGRFM{rnd}": bm, f"BEGRFY{rnd}": by,
            f"ENDRFM{rnd}": em, f"ENDRFY{rnd}": ey,
        })  # fmt: skip
    return row


Y = 2023
PEOPLE = [
    # Full year: three contiguous rounds that start in the previous year and end in the next.
    person(Y, "full_year", {31: (1, 1, Y, 4, Y), 42: (1, 4, Y, 8, Y), 53: (1, 8, Y, 12, Y)}),
    # Reference period starts before the year and ends after it.
    person(Y, "spans_year", {31: (1, 9, Y - 1, 12, Y), 42: (3, -1, -1, -1, -1)}),
    # Birth: first eligible round is 4/2 and starts in May.
    person(Y, "birth_may", {42: (1, 5, Y, 8, Y), 53: (1, 8, Y, 12, Y)}),
    # Death or leaving: the last eligible round ends in March.
    person(Y, "left_march", {31: (1, 1, Y, 3, Y), 42: (3, -1, -1, -1, -1)}),
    # A gap round (not in a household unit for 4/2) adds no months.
    person(Y, "gap_round", {31: (1, 1, Y, 3, Y), 42: (4, -1, -1, -1, -1), 53: (1, 9, Y, 12, Y)}),
    # Never eligible in any round.
    person(Y, "never_eligible", {}),
    # An eligible round with a missing date counts nothing, the singular test catches it.
    person(Y, "missing_dates", {31: (1, None, None, None, None)}),
    # Same person id in the other year is a separate person-year.
    person(Y - 1, "full_year", {31: (1, 1, Y - 1, 12, Y - 1)}),
]


@pytest.fixture(scope="module")
def exposure(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("exposure")
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        'name: "fixture_project"\nversion: "1.0.0"\nconfig-version: 2\nprofile: "fixture"\n'
        'model-paths: ["models"]\n',
        encoding="utf-8",
    )
    db = tmp_path / "fixture.duckdb"
    profile = (
        "fixture:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        f'      path: "{db.as_posix()}"\n'
    )
    (project / "profiles.yml").write_text(profile, encoding="utf-8")
    (project / "models" / "int_person_clean.sql").write_text("select * from main.fx_clean\n")
    shutil.copy(MODEL, project / "models" / MODEL.name)

    con = duckdb.connect(str(db))
    types = ", ".join(f'"{c}" {"VARCHAR" if c == "DUPERSID" else "BIGINT"}' for c in COLUMNS)
    con.execute(f"CREATE TABLE main.fx_clean ({types})")
    names = ", ".join(f'"{c}"' for c in COLUMNS)
    marks = ", ".join("?" for _ in COLUMNS)
    for row in PEOPLE:
        con.execute(
            f"INSERT INTO main.fx_clean ({names}) VALUES ({marks})", [row[c] for c in COLUMNS]
        )
    con.close()

    run = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "run", "--project-dir", str(project),
         "--profiles-dir", str(project)],
        capture_output=True, text=True, cwd=tmp_path,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    con = duckdb.connect(str(db), read_only=True)
    result = con.execute("SELECT * FROM int_person_exposure ORDER BY year, DUPERSID").fetchdf()
    con.close()
    return result.set_index(["year", "DUPERSID"])


def months(exposure, year, name):
    return int(exposure.loc[(year, name), "exposure_months"])


def test_full_year_person_has_12_months_and_exposure_1(exposure):
    assert months(exposure, Y, "full_year") == 12
    assert exposure.loc[(Y, "full_year"), "exposure"] == 1.0


def test_a_period_that_starts_before_the_year_counts_from_january(exposure):
    assert months(exposure, Y, "spans_year") == 12


def test_birth_in_may_has_8_months(exposure):
    assert months(exposure, Y, "birth_may") == 8
    assert exposure.loc[(Y, "birth_may"), "exposure"] == pytest.approx(8 / 12)


def test_leaving_in_march_has_3_months(exposure):
    assert months(exposure, Y, "left_march") == 3
    assert exposure.loc[(Y, "left_march"), "exposure"] == 0.25


def test_a_gap_round_adds_no_months_and_shared_boundary_months_count_once(exposure):
    # Jan to March from round 3/1, then September to December from round 5/3.
    assert months(exposure, Y, "gap_round") == 7


def test_a_person_never_eligible_has_zero_exposure_not_null(exposure):
    assert months(exposure, Y, "never_eligible") == 0
    assert exposure.loc[(Y, "never_eligible"), "exposure"] == 0.0


def test_an_eligible_round_with_missing_dates_counts_nothing(exposure):
    assert months(exposure, Y, "missing_dates") == 0


def test_the_same_person_in_two_years_is_two_rows(exposure):
    assert months(exposure, Y - 1, "full_year") == 12
    assert len(exposure) == len(PEOPLE)
