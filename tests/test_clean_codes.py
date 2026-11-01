"""Tests for the reserved-code treatment in int_person_clean (issue #12).

The model SQL is run on a throwaway dbt project whose staging tables hold hand-made rows, one row
per rule. The staging column list comes from the real staged table, so this needs the data loaded
and dbt built once. It skips otherwise.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from health_pricing.data.load import DUCKDB_PATH

REPO = Path(__file__).resolve().parents[1]


def _staging_is_built() -> bool:
    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'stg_fyc_2022'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


pytestmark = pytest.mark.skipif(not _staging_is_built(), reason="run the load script and dbt build")

# One hand-made person per case. Columns not listed are null.
CASES = {
    "child": dict(age=5, AGELAST=5, OFTSMK53=-1, PHYEXE53=-1, HIBPDX=-1, CANCERDX=-1, ASTHDX=-1),
    "adult_minus1": dict(age=40, AGELAST=40, OFTSMK53=-1, HIBPDX=-1, ASTHDX=-1, DIABDX_M18=-1),
    "adult_refused": dict(age=40, AGELAST=40, CHDDX=-7, PHYEXE53=-7, OFTSMK53=-7),
    "adult_dont_know": dict(age=40, AGELAST=40, ANGIDX=-8, ASTHDX=-8, SEX=-8),
    "adult_cannot_compute": dict(age=40, AGELAST=40, CANCERDX=-15, OBTOTV=-15, ERTOT=-15),
    "answers": dict(age=40, AGELAST=40, HIBPDX=1, CHDDX=2, PHYEXE53=2, OFTSMK53=3, ASTHDX=1),
    "age_85": dict(age=85, AGELAST=85),
    "age_84": dict(age=84, AGELAST=84),
    "age_missing_filled": dict(age=-1, AGELAST=70),
    "age_missing_both": dict(age=-1, AGELAST=-1),
    "rounds_latest": dict(age=40, AGELAST=40, RTHLTH53=-1, RTHLTH42=3, RTHLTH31=1, MNHLTH53=4),
    "rounds_all_null": dict(age=40, AGELAST=40, RTHLTH53=-1, RTHLTH42=-7, RTHLTH31=-8),
    "region_year_end": dict(age=40, AGELAST=40, region=2, REGION53=3, ELGRND=1),
    "region_left": dict(
        age=-1, AGELAST=60, region=-1, REGION53=-1, REGION42=4, REGION31=1, ELGRND=3
    ),
    "region_left_round1_only": dict(age=-1, AGELAST=60, region=-1, REGION31=3, ELGRND=3),
    "region_none": dict(age=40, AGELAST=40, region=-1, REGION31=-7),
    "other_codes": dict(
        age=40, AGELAST=40, region=-1, SEX=-7, ENDRFM53=-1, ENDRFM42=-8, ELGRND53=-1
    ),
}  # fmt: skip


@pytest.fixture(scope="module")
def cleaned(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("clean")
    real = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    columns = real.execute("DESCRIBE stg_fyc_2022").fetchall()
    real.close()

    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    shutil.copytree(REPO / "dbt" / "macros", project / "macros")
    (project / "dbt_project.yml").write_text(
        'name: "fixture_project"\nversion: "1.0.0"\nconfig-version: 2\nprofile: "fixture"\n'
        'model-paths: ["models"]\nmacro-paths: ["macros"]\n',
        encoding="utf-8",
    )
    db = tmp_path / "fixture.duckdb"
    profile = (
        "fixture:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        f'      path: "{db.as_posix()}"\n'
    )
    (project / "profiles.yml").write_text(profile, encoding="utf-8")
    for year in (2022, 2023):
        (project / "models" / f"stg_fyc_{year}.sql").write_text(f"select * from main.fx_{year}\n")
    shutil.copy(
        REPO / "dbt" / "models" / "intermediate" / "int_person_clean.sql", project / "models"
    )

    con = duckdb.connect(str(db))
    ddl = ", ".join(f'"{name}" {kind}' for name, kind, *_ in columns)
    for year in (2022, 2023):
        con.execute(f"CREATE TABLE main.fx_{year} ({ddl})")

    def insert(table, row):
        names = ", ".join(f'"{k}"' for k in row)
        marks = ", ".join("?" for _ in row)
        con.execute(f"INSERT INTO main.{table} ({names}) VALUES ({marks})", list(row.values()))

    for number, (case, values) in enumerate(CASES.items(), start=1):
        insert("fx_2022", {"year": 2022, "DUPERSID": case, "DUID": number, **values})
    insert("fx_2023", {"year": 2023, "DUPERSID": "y2023", "age": 20, "AGELAST": 20, "HIBPDX": 1})
    con.close()

    run = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "run", "--project-dir", str(project),
         "--profiles-dir", str(project)],
        capture_output=True, text=True, cwd=tmp_path,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr

    con = duckdb.connect(str(db), read_only=True)
    result = con.execute("SELECT * FROM int_person_clean").fetchdf().set_index("DUPERSID")
    con.close()
    return result


def _value(cleaned, case, column):
    value = cleaned.loc[case, column]
    return None if pd.isna(value) else value


def test_minus_1_for_a_child_is_not_applicable_on_adult_only_questions(cleaned):
    for column in ("OFTSMK53", "PHYEXE53", "HIBPDX", "CANCERDX"):
        assert _value(cleaned, "child", column) == "not_applicable", column


def test_minus_1_on_a_question_asked_at_any_age_is_unknown_even_for_a_child(cleaned):
    assert _value(cleaned, "child", "ASTHDX") == "unknown"


def test_minus_1_for_an_adult_is_unknown(cleaned):
    for column in ("OFTSMK53", "HIBPDX", "ASTHDX", "DIABDX_M18"):
        assert _value(cleaned, "adult_minus1", column) == "unknown", column


def test_minus_7_is_null(cleaned):
    for column in ("CHDDX", "PHYEXE53", "OFTSMK53"):
        assert _value(cleaned, "adult_refused", column) is None, column
    assert _value(cleaned, "other_codes", "SEX") is None


def test_minus_8_is_null(cleaned):
    for column in ("ANGIDX", "ASTHDX", "SEX"):
        assert _value(cleaned, "adult_dont_know", column) is None, column


def test_minus_15_is_null(cleaned):
    for column in ("CANCERDX", "OBTOTV", "ERTOT"):
        assert _value(cleaned, "adult_cannot_compute", column) is None, column


def test_answers_are_recoded_to_text_levels(cleaned):
    assert _value(cleaned, "answers", "HIBPDX") == "1"
    assert _value(cleaned, "answers", "CHDDX") == "0"
    assert _value(cleaned, "answers", "PHYEXE53") == "0"
    assert _value(cleaned, "answers", "OFTSMK53") == "3"
    assert _value(cleaned, "answers", "ASTHDX") == "1"


def test_age_85_is_kept_and_flagged_as_top_coded(cleaned):
    assert _value(cleaned, "age_85", "age") == 85
    assert bool(cleaned.loc["age_85", "age_topcoded"]) is True
    assert bool(cleaned.loc["age_84", "age_topcoded"]) is False


def test_missing_year_end_age_is_filled_from_agelast_with_a_flag(cleaned):
    assert _value(cleaned, "age_missing_filled", "age") == 70
    assert _value(cleaned, "age_missing_filled", "age_source") == "last_eligible"
    assert _value(cleaned, "age_85", "age_source") == "year_end"


def test_age_stays_null_when_both_sources_are_missing(cleaned):
    assert _value(cleaned, "age_missing_both", "age") is None
    assert _value(cleaned, "age_missing_both", "age_source") is None


def test_health_status_uses_the_latest_valid_round(cleaned):
    assert _value(cleaned, "rounds_latest", "rthlth") == 3
    assert _value(cleaned, "rounds_latest", "rthlth_round") == 42
    assert _value(cleaned, "rounds_latest", "mnhlth") == 4


def test_health_status_is_null_when_every_round_is_invalid(cleaned):
    assert _value(cleaned, "rounds_all_null", "rthlth") is None
    assert _value(cleaned, "rounds_all_null", "rthlth_round") is None


def test_region_minus_1_is_null_and_round_dates_keep_minus_1_but_drop_minus_8(cleaned):
    assert _value(cleaned, "other_codes", "region") is None
    assert _value(cleaned, "other_codes", "ENDRFM53") == -1
    assert _value(cleaned, "other_codes", "ELGRND53") == -1
    assert _value(cleaned, "other_codes", "ENDRFM42") is None


def test_both_years_are_stacked(cleaned):
    assert set(cleaned["year"]) == {2022, 2023}
    assert _value(cleaned, "y2023", "HIBPDX") == "1"


def test_region_uses_the_year_end_value_when_valid(cleaned):
    assert _value(cleaned, "region_year_end", "region") == 2
    assert _value(cleaned, "region_year_end", "region_source") == "year_end"


def test_region_for_a_leaver_uses_the_latest_valid_round_and_is_flagged(cleaned):
    assert _value(cleaned, "region_left", "region") == 4
    assert _value(cleaned, "region_left", "region_source") == "last_round"
    assert _value(cleaned, "region_left_round1_only", "region") == 3


def test_region_stays_null_when_no_round_has_a_valid_region(cleaned):
    assert _value(cleaned, "region_none", "region") is None
    assert _value(cleaned, "region_none", "region_source") is None


def test_left_survey_early_follows_the_year_end_eligibility(cleaned):
    assert bool(cleaned.loc["region_left", "left_survey_early"]) is True
    assert bool(cleaned.loc["region_year_end", "left_survey_early"]) is False
