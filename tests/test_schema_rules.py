"""Tests for the value-level rules in dbt/models/staging/schema.yml (issue #10).

Two checks. The rules in the file must match AHRQ's VALUE blocks, so a drifting rule fails here.
And a rule of each shape must fail on a bad value, shown on a small throwaway dbt project.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
import yaml

from health_pricing.data.sas_layout import extract_value_block, parse_value_rules

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "dbt" / "models" / "staging" / "schema.yml"
SU_FILES = {2022: REPO / "data/raw/h243su.txt", 2023: REPO / "data/raw/h251su.txt"}
YY = {2022: "22", 2023: "23"}
RENAMED = {"age": "AGE{yy}X", "region": "REGION{yy}", "inscov": "INSCOV{yy}"}

# The variables issue #10 names, in the staged names.
ISSUE_10_VARIABLES = {
    "DUPERSID", "DUID", "PID", "PANEL", "VARSTR", "VARPSU", "age", "SEX", "region", "inscov",
    "OFTSMK53", "PHYEXE53", "ASTHDX", "DIABDX_M18", "HIBPDX", "CHDDX", "ANGIDX", "MIDX",
    "OHRTDX", "STRKDX", "CHOLDX", "CANCERDX", "ARTHDX",
    *(f"{stem}{rnd}" for stem in ("RTHLTH", "MNHLTH") for rnd in (31, 42, 53)),
}  # fmt: skip

needs_codebook = pytest.mark.skipif(
    not all(p.exists() for p in SU_FILES.values()),
    reason="AHRQ SAS statement files not downloaded",
)


def _rules():
    models = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))["models"]
    return {m["name"]: {c["name"]: c["data_tests"] for c in m["columns"]} for m in models}


def _test_args(test):
    ((name, body),) = test.items()
    return name, body["arguments"], body.get("config", {})


# The variables issue #11 names, in the staged names. The first five carry -15 (cannot be
# computed) in the codebook. The rest carry no reserved code at all.
ISSUE_11_COUNTS_WITH_RESERVED = {"OBTOTV", "OPTOTV", "ERTOT", "IPDIS", "OBDRV"}
ISSUE_11_NO_RESERVED = {
    "IPNGTD", "RXTOT", "TOTEXP", "TOTSLF", "TOTMCR", "TOTMCD", "TOTPRV", "TOTPTR", "OBVEXP",
    "OBDEXP", "OPTEXP", "ERTEXP", "IPTEXP", "RXEXP", "perwt",
}  # fmt: skip
ISSUE_11_VARIABLES = ISSUE_11_COUNTS_WITH_RESERVED | ISSUE_11_NO_RESERVED
RENAMED["perwt"] = "PERWT{yy}F"
RENAMED.update({c: c + "{yy}" for c in ISSUE_11_VARIABLES - {"perwt"}})


def test_every_issue_10_variable_has_a_rule_in_both_years():
    rules = _rules()
    for year in (2022, 2023):
        assert set(rules[f"stg_fyc_{year}"]) == ISSUE_10_VARIABLES | ISSUE_11_VARIABLES


@needs_codebook
@pytest.mark.parametrize("year", [2022, 2023])
def test_rules_match_the_codebook(year):
    for column, tests in _rules()[f"stg_fyc_{year}"].items():
        sas = RENAMED.get(column, column).format(yy=YY[year])
        expected = parse_value_rules(extract_value_block(SU_FILES[year], sas))
        shaped = [_test_args(t) for t in tests if isinstance(t, dict)]
        assert shaped, column
        name, args, config = shaped[0]
        if column in ISSUE_11_VARIABLES:
            # Zero or more, with the codebook's own reserved codes allowed and nothing else.
            assert name == "dbt_utils.accepted_range", column
            assert (args["min_value"], "max_value" in args) == (0, False), column
            assert expected.reserved == ((-15,) if column in ISSUE_11_COUNTS_WITH_RESERVED else ())
            if expected.reserved:
                assert config["where"] == f"{column} not in (-15)", column
            else:
                assert "where" not in config, column
        elif expected.ranges:
            assert name == "dbt_utils.accepted_range", column
            low = min(r[0] for r in expected.ranges)
            high = max(r[1] for r in expected.ranges)
            assert (args["min_value"], args["max_value"]) == (low, high), column
            if expected.singles:
                codes = ", ".join(str(c) for c in expected.singles)
                assert config["where"] == f"{column} not in ({codes})", column
            else:
                assert "where" not in config, column
        else:
            assert name == "accepted_values", column
            assert args["values"] == list(expected.singles), column


@needs_codebook
def test_reserved_codes_in_rules_match_the_variable_mapping_groups():
    """Spot the year-dependent case the mapping document warns about, PID."""
    rules = _rules()
    pid_2022 = _test_args(rules["stg_fyc_2022"]["PID"][0])
    pid_2023 = _test_args(rules["stg_fyc_2023"]["PID"][0])
    assert "where" in pid_2022[2]
    assert "where" not in pid_2023[2]


# --- A rule of each shape fails on a bad value -------------------------------------------

FIXTURE_SCHEMA = """\
version: 2
models:
  - name: fixture
    columns:
      - name: age
        data_tests:
          - dbt_utils.accepted_range:
              arguments:
                min_value: 0
                max_value: 85
              config:
                where: "age not in (-1)"
      - name: sex
        data_tests:
          - accepted_values:
              arguments:
                values: [-1, 1, 2]
                quote: false
"""


def _run_dbt_test(tmp_path: Path, rows: list[tuple[int, int]]) -> tuple[int, str]:
    packages = REPO / "dbt" / "dbt_packages"
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    shutil.copytree(packages, project / "dbt_packages")
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
    for name in ("packages.yml", "package-lock.yml"):
        shutil.copy(REPO / "dbt" / name, project / name)
    (project / "models" / "fixture.sql").write_text("select * from main.fixture_source\n")
    (project / "models" / "schema.yml").write_text(FIXTURE_SCHEMA, encoding="utf-8")
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE main.fixture_source (age BIGINT, sex BIGINT)")
    con.executemany("INSERT INTO main.fixture_source VALUES (?, ?)", rows)
    con.close()
    run = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "build", "--project-dir", str(project),
         "--profiles-dir", str(project)],
        capture_output=True, text=True, cwd=tmp_path,
    )  # fmt: skip
    return run.returncode, run.stdout + run.stderr


needs_dbt_utils = pytest.mark.skipif(
    not (REPO / "dbt" / "dbt_packages").exists(), reason="run dbt deps first"
)


@needs_dbt_utils
def test_good_values_pass(tmp_path):
    code, output = _run_dbt_test(tmp_path, [(-1, -1), (0, 1), (85, 2)])
    assert code == 0, output


@needs_dbt_utils
@pytest.mark.parametrize("row", [(86, 1), (-5, 1), (30, 3), (30, 0)])
def test_bad_values_fail(tmp_path, row):
    code, output = _run_dbt_test(tmp_path, [(30, 1), row])
    assert code != 0, output
    assert "FAIL 1" in output, output
