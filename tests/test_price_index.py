"""Tests for the PCE-Health price index download and the committed CSV (issue #16)."""

import json
import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

import health_pricing.data.price_index as price_index

REPO = Path(__file__).resolve().parents[1]

FAKE_KEY = "FAKE-KEY-0000-1111-2222-333344445555"


def _fake_response(rows):
    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "BEAAPI": {
                    "Request": {
                        "RequestParam": [{"ParameterName": "USERID", "ParameterValue": FAKE_KEY}]
                    },
                    "Results": {"Data": rows},
                }
            }

    return Response()


def _row(year, value, line="37", description="Health"):
    return {
        "TimePeriod": str(year), "SeriesCode": "DHLTRG", "LineNumber": line,
        "LineDescription": description, "DataValue": value,
    }  # fmt: skip


def test_committed_csv_matches_its_recorded_checksum():
    meta = json.loads(price_index.META_PATH.read_text(encoding="utf-8"))
    assert meta["sha256"] == price_index.sha256_of(price_index.CSV_PATH)
    assert meta["table_name"] == "T20504"
    assert "UserID=<BEA_API_KEY>" in meta["request_url"]
    assert meta["retrieved_on"]


def test_committed_csv_is_the_health_line_with_2022_and_2023():
    frame = pd.read_csv(price_index.CSV_PATH)
    assert list(frame.columns) == price_index.COLUMNS
    assert set(frame["line_description"]) == {"Health"}
    assert set(frame["line_number"]) == {37}
    assert frame["year"].is_unique
    values = frame.set_index("year")["index_value"]
    assert values.loc[2022] == pytest.approx(110.256)
    assert values.loc[2023] == pytest.approx(113.121)
    assert (values > 0).all()


def test_fetch_keeps_only_the_health_line_and_never_stores_the_key(monkeypatch, tmp_path):
    rows = [_row(2022, "110.256"), _row(2023, "1,113.121"), _row(2023, "99", "38", "Other")]
    monkeypatch.setattr(price_index.requests, "get", lambda *a, **k: _fake_response(rows))
    frame = price_index.fetch_pce_health(api_key=FAKE_KEY)
    assert list(frame["year"]) == [2022, 2023]
    assert frame.loc[1, "index_value"] == pytest.approx(1113.121)

    meta = price_index.save(frame, tmp_path / "x.csv", tmp_path / "x.meta.json")
    for path in tmp_path.iterdir():
        assert FAKE_KEY not in path.read_text(encoding="utf-8")
    assert FAKE_KEY not in json.dumps(meta)


def test_a_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("BEA_API_KEY", raising=False)
    with pytest.raises(price_index.PriceIndexError, match="BEA_API_KEY is not set"):
        price_index.fetch_pce_health()


def test_errors_never_repeat_the_key(monkeypatch):
    def boom(*args, **kwargs):
        raise price_index.requests.ConnectionError(f"failed for UserID={FAKE_KEY}")

    monkeypatch.setattr(price_index.requests, "get", boom)
    with pytest.raises(price_index.PriceIndexError) as error:
        price_index.fetch_pce_health(api_key=FAKE_KEY)
    assert FAKE_KEY not in str(error.value)


def test_a_line_that_is_not_health_is_rejected(monkeypatch):
    rows = [_row(2022, "110.256", description="Goods")]
    monkeypatch.setattr(price_index.requests, "get", lambda *a, **k: _fake_response(rows))
    with pytest.raises(price_index.PriceIndexError):
        price_index.fetch_pce_health(api_key=FAKE_KEY)


@pytest.mark.skipif(
    not os.environ.get("BEA_API_KEY"), reason="run with `uv run --env-file .env pytest` to check"
)
def test_the_real_key_appears_in_no_tracked_file():
    key = os.environ["BEA_API_KEY"]
    files = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    leaked = [f for f in files if key in (REPO / f).read_bytes().decode("utf-8", errors="ignore")]
    assert leaked == []
