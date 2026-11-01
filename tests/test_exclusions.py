"""Tests for the exclusion rules, quarantine and log (issue #14).

The model SQL runs on a throwaway dbt project whose cleaned person and exposure tables hold
hand-made rows, one per rule, so each reason and the log shares can be checked by hand.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "dbt" / "models" / "intermediate"

CLEAN_COLUMNS = (
    "year BIGINT, DUPERSID VARCHAR, DUID BIGINT, perwt DOUBLE, age BIGINT, SEX BIGINT, "
    "region BIGINT, inscov BIGINT, TOTEXP BIGINT, TOTSLF BIGINT, TOTMCR BIGINT, TOTMCD BIGINT, "
    "TOTPRV BIGINT, TOTPTR BIGINT"
)


def clean_row(person, **override):
    row = dict(
        year=2022, DUPERSID=person, DUID=1, perwt=1000.0, age=40, SEX=1, region=2, inscov=1,
        TOTEXP=100, TOTSLF=10, TOTMCR=10, TOTMCD=10, TOTPRV=10, TOTPTR=10,
    )  # fmt: skip
    row.update(override)
    return row


# 20 ordinary people, then one person per rule. The 2022 total expenditure is 2,000 + 8 x 100.
CLEAN = [clean_row(f"ok{i}") for i in range(20)] + [
    clean_row("zero_weight", perwt=0.0, TOTEXP=400),
    clean_row("no_exposure"),
    clean_row("no_region", region=None),
    clean_row("negative_cost", TOTSLF=-5),
    clean_row("zero_weight_and_no_region", perwt=0.0, region=None, TOTEXP=50),
    clean_row("dup"),
    clean_row("dup"),
    clean_row("other_year", year=2023),
]
EXPOSURE = [
    {"year": r["year"], "DUPERSID": r["DUPERSID"], "months": 12, "exposure": 1.0} for r in CLEAN
]
for e in EXPOSURE:
    if e["DUPERSID"] == "no_exposure":
        e["months"], e["exposure"] = 0, 0.0
EXPOSURE = list({(e["year"], e["DUPERSID"]): e for e in EXPOSURE}.values())


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("exclusions")
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
    (project / "models" / "int_person_exposure.sql").write_text("select * from main.fx_exposure\n")
    for name in ("int_person_flags", "quarantine_person", "int_person_retained", "exclusion_log"):
        shutil.copy(MODELS / f"{name}.sql", project / "models" / f"{name}.sql")

    con = duckdb.connect(str(db))
    con.execute(f"CREATE TABLE main.fx_clean ({CLEAN_COLUMNS})")
    names = list(CLEAN[0])
    for row in CLEAN:
        marks = ", ".join("?" for _ in names)
        con.execute(
            f"INSERT INTO main.fx_clean ({', '.join(names)}) VALUES ({marks})",
            [row[n] for n in names],
        )
    con.execute(
        "CREATE TABLE main.fx_exposure (year BIGINT, DUPERSID VARCHAR, "
        "exposure_months BIGINT, exposure DOUBLE)"
    )
    for e in EXPOSURE:
        con.execute(
            "INSERT INTO main.fx_exposure VALUES (?, ?, ?, ?)",
            [e["year"], e["DUPERSID"], e["months"], e["exposure"]],
        )
    con.close()

    run = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "run", "--project-dir", str(project),
         "--profiles-dir", str(project)],
        capture_output=True, text=True, cwd=tmp_path,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    con = duckdb.connect(str(db), read_only=True)
    out = {
        "quarantine": con.execute("SELECT * FROM quarantine_person").fetchdf(),
        "retained": con.execute("SELECT * FROM int_person_retained").fetchdf(),
        "log": con.execute("SELECT * FROM exclusion_log").fetchdf(),
        "flags": con.execute("SELECT count(*) FROM int_person_flags").fetchone()[0],
    }
    con.close()
    return out


def reason_of(result, person):
    quarantine = result["quarantine"]
    return list(quarantine.loc[quarantine["DUPERSID"] == person, "reason_code"])


def test_zero_weight_is_quarantined_with_the_approved_reason(result):
    assert reason_of(result, "zero_weight") == ["not_in_person_level_analytic_population"]
    quarantine = result["quarantine"]
    reason = quarantine.loc[quarantine["DUPERSID"] == "zero_weight", "reason"].iloc[0]
    assert reason == "not in person-level analytic population"


def test_each_data_quality_rule_quarantines_its_person(result):
    assert reason_of(result, "no_exposure") == ["no_exposure"]
    assert reason_of(result, "no_region") == ["missing_core_factor"]
    assert reason_of(result, "negative_cost") == ["negative_expenditure"]


def test_a_person_flagged_by_two_rules_is_quarantined_once_under_the_first(result):
    assert reason_of(result, "zero_weight_and_no_region") == ["missing_core_factor"]


def test_the_second_copy_of_a_duplicate_is_quarantined(result):
    assert reason_of(result, "dup") == ["duplicate_person_year"]
    retained = result["retained"]
    assert (retained["DUPERSID"] == "dup").sum() == 1


def test_retained_plus_quarantined_equals_all_person_years(result):
    assert len(result["retained"]) + len(result["quarantine"]) == len(CLEAN) == result["flags"]
    overlap = set(result["retained"]["DUPERSID"]) & set(result["quarantine"]["DUPERSID"])
    assert overlap == {"dup"}  # one copy kept, one held out


def test_ordinary_people_are_retained(result):
    assert {f"ok{i}" for i in range(20)} <= set(result["retained"]["DUPERSID"])
    assert "other_year" in set(result["retained"]["DUPERSID"])


def test_the_log_counts_flagged_and_quarantined_persons_by_rule(result):
    log = result["log"]
    row = log[(log["year"] == 2022) & (log["rule_code"] == "missing_core_factor")].iloc[0]
    assert row["persons_flagged"] == 2  # no_region and zero_weight_and_no_region
    assert row["persons_quarantined"] == 2
    row = log[
        (log["year"] == 2022) & (log["rule_code"] == "not_in_person_level_analytic_population")
    ].iloc[0]
    assert row["persons_flagged"] == 2  # zero_weight and zero_weight_and_no_region
    assert row["persons_quarantined"] == 1  # the second is held out under the first reason


def test_the_log_gives_the_share_of_persons_and_cost(result):
    log = result["log"]
    row = log[(log["year"] == 2022) & (log["rule_code"] == "no_exposure")].iloc[0]
    assert row["share_of_persons"] == pytest.approx(1 / 27)  # 27 person-years in 2022
    assert row["kind"] == "data_quality"


def test_rules_above_1_percent_are_marked_for_a_decision_unless_approved(result):
    log = result["log"]
    by_rule = {r["rule_code"]: r["gate3_decision"] for _, r in log[log["year"] == 2022].iterrows()}
    assert by_rule["not_in_person_level_analytic_population"] == "approved 2026-11-01"
    assert by_rule["no_exposure"] == "needs user decision"  # 1 of 27 is over 1%
    assert by_rule["duplicate_person_year"] != "not needed (1% or less)"
