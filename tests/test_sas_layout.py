from pathlib import Path

import pandas as pd

from health_pricing.data.sas_layout import parse_layout, read_fixed_width

# Mirrors the structure of AHRQ's real SAS program-statement files closely enough to test the
# parser without depending on a network fetch: an "INPUT @..." block, one field per line, ending
# at a line that is just ";", with a mix of numeric, implied-decimal and character fields.
FIXTURE_SU_TXT = """\
D.  SAS Statements

This section contains SAS INPUT, LABEL, FORMAT, and VALUE statements.

* INPUT STATEMENTS;
INFILE IN LRECL=23;

INPUT @1      DUID                              7.0
      @8      DUPERSID                         $10.0
      @18     AGE23X                            2.0
      @20     PERWT23F                          4.2
;


* FORMAT STATEMENTS;
FORMAT DUID DUIDF.;
"""


def test_parse_layout(tmp_path: Path):
    su_path = tmp_path / "fixture_su.txt"
    su_path.write_text(FIXTURE_SU_TXT, encoding="latin-1")

    fields = parse_layout(su_path)
    by_name = {f.name: f for f in fields}

    assert by_name["DUID"].start == 1
    assert by_name["DUID"].width == 7
    assert by_name["DUID"].decimals == 0
    assert by_name["DUID"].is_char is False

    assert by_name["DUPERSID"].start == 8
    assert by_name["DUPERSID"].width == 10
    assert by_name["DUPERSID"].is_char is True

    assert by_name["PERWT23F"].start == 20
    assert by_name["PERWT23F"].width == 4
    assert by_name["PERWT23F"].decimals == 2
    assert by_name["PERWT23F"].colspec == (19, 23)


def test_read_fixed_width_applies_implied_decimals(tmp_path: Path):
    su_path = tmp_path / "fixture_su.txt"
    su_path.write_text(FIXTURE_SU_TXT, encoding="latin-1")
    fields = parse_layout(su_path)

    # One row: DUID=2460002, DUPERSID=2460002101, AGE23X=45, PERWT23F="1234" meaning 12.34
    # (4.2 informat: 4-character field, 2 implied decimals).
    dat_path = tmp_path / "fixture.dat"
    dat_path.write_text("2460002" + "2460002101" + "45" + "1234\n", encoding="latin-1")

    df = read_fixed_width(dat_path, fields)

    assert df.loc[0, "DUID"] == 2460002
    assert df.loc[0, "DUPERSID"] == "2460002101"
    assert df.loc[0, "AGE23X"] == 45
    assert df.loc[0, "PERWT23F"] == 12.34


def test_read_fixed_width_treats_reserved_negative_codes_as_numeric(tmp_path: Path):
    su_path = tmp_path / "fixture_su.txt"
    su_path.write_text(FIXTURE_SU_TXT, encoding="latin-1")
    fields = parse_layout(su_path)

    # AGE23X = -1 (inapplicable), right-aligned in its 2-character field.
    dat_path = tmp_path / "fixture.dat"
    dat_path.write_text("2460002" + "2460002101" + "-1" + "1234\n", encoding="latin-1")

    df = read_fixed_width(dat_path, fields)
    assert df.loc[0, "AGE23X"] == -1
    assert pd.notna(df.loc[0, "AGE23X"])


def test_read_fixed_width_literal_decimal_point_overrides_implied_decimals(tmp_path: Path):
    su_path = tmp_path / "fixture_su.txt"
    su_path.write_text(FIXTURE_SU_TXT, encoding="latin-1")
    fields = parse_layout(su_path)

    # PERWT23F is 4.2, but AHRQ's event and weight fields hold a literal point, which SAS keeps
    # as written. Dividing again by 100 would give 0.12 here (the M1 loader bug).
    dat_path = tmp_path / "fixture.dat"
    dat_path.write_text("2460002" + "2460002101" + "45" + "1.23" + chr(10), encoding="latin-1")

    df = read_fixed_width(dat_path, fields)
    assert df.loc[0, "PERWT23F"] == 1.23


def test_parse_value_rules_splits_singles_and_ranges():
    from health_pricing.data.sas_layout import parse_value_rules

    block = """\
  -1 = "-1 INAPPLICABLE"
  0 - 4 = "0-4 AGE"
  65 - 85 = "65-85 AGE"
"""
    rules = parse_value_rules(block)
    assert rules.singles == (-1,)
    assert rules.reserved == (-1,)
    assert rules.ranges == ((0, 4), (65, 85))


def test_parse_value_rules_handles_character_id_ranges_and_negative_range_end():
    from health_pricing.data.sas_layout import parse_value_rules

    rules = parse_value_rules("  '2790002101' - '2819793102' = \"VALID ID\"\n  1 = \"YES\"")
    assert rules.ranges == (("'2790002101'", "'2819793102'"),)
    assert rules.singles == (1,)
    assert rules.reserved == ()
