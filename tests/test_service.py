"""Tests for the pricing web service and the command line entry points (M10-lite)."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pandas as pd
import predict
import pytest
import uvicorn

from health_pricing.rating import book as bk
from health_pricing.rating import engine
from health_pricing.service import app as service
from health_pricing.service import openapi

GOLDEN = engine.OUTPUTS / "v1" / "golden_cases.csv"
PROFILE_FIELDS = ["age", "region", *predict.CONDITIONS]
NONE = dict.fromkeys(predict.CONDITIONS, "0")


@pytest.fixture(scope="module")
def server():
    if not GOLDEN.exists():
        pytest.skip("run python -m health_pricing.publish")
    if os.environ.get("SERVICE_URL"):  # an already running service, for example docker run
        yield os.environ["SERVICE_URL"].rstrip("/")
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(service.app, host="127.0.0.1", port=port, log_level="warning")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    for _ in range(100):
        if running.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


def call(base, path, body=None):
    """Return the status and the JSON body of a call."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def golden_profiles():
    table = pd.read_csv(GOLDEN, dtype={"region": str, **dict.fromkeys(predict.CONDITIONS, str)})
    return table


def test_the_service_returns_every_golden_case_premium(server):
    golden = golden_profiles()
    assert len(golden) >= 30
    for row in golden.to_dict("records"):
        profile = {k: row[k] for k in PROFILE_FIELDS}
        profile["age"] = int(profile["age"])
        status, body = call(server, "/quote", profile)
        assert status == 200, (row["case_id"], body)
        assert body["premium_usd"] == pytest.approx(row["expected_premium_usd"], rel=1e-9)
        assert body["premium_illustrative_gbp"] == pytest.approx(
            row["expected_premium_gbp"], rel=1e-9
        )
        product = 1.0
        for line in body["breakdown"]:
            product *= line["factor"]
        assert product == pytest.approx(body["premium_illustrative_gbp"])
        assert body["illustrative_label"] == engine.GBP_LABEL


def test_health_and_the_golden_label(server):
    status, body = call(server, "/health")
    assert status == 200 and body["status"] == "ok" and body["model_version"] == "v1"
    label = "regression baseline, provisional until the Excel reconciliation"
    assert body["golden_cases_status"] == label
    assert body["description"].startswith("v1: 2022-fitted") and "lite" not in body["description"]


def test_quote_rejects_invalid_and_not_permitted_profiles(server):
    base = {"age": 40, "region": "3", **NONE}
    for extra, message in (
        ({"sex": "F"}, "not permitted"),
        ({"region": "9"}, "not a level"),
        ({"age": 130}, "between"),
        ({"colour": "blue"}, "Unknown"),
    ):
        status, body = call(server, "/quote", {**base, **extra})
        assert status == 422 and message in json.dumps(body), (extra, body)
    status, body = call(server, "/quote", {"age": 40})
    assert status == 422


def test_quote_accepts_numbers_and_prices_controls_at_reference(server):
    profile = {"age": 40, "region": 3, **{**NONE, "CANCERDX": 1}}
    plain = call(server, "/quote", profile)[1]
    smoker = call(server, "/quote", {**profile, "OFTSMK53": "1"})[1]
    assert plain["premium_usd"] == smoker["premium_usd"]
    assert smoker["priced_at_reference"] == ["OFTSMK53"]
    double = call(server, "/quote", {**profile, "exposure": 2})[1]
    assert double["premium_usd"] == pytest.approx(2 * plain["premium_usd"])


def test_relativities_endpoint(server):
    status, body = call(server, "/relativities")
    assert status == 200
    table = pd.DataFrame(body["relativities"])
    published = pd.read_csv(engine.OUTPUTS / "v1" / "relativities.csv", dtype={"level": str})
    assert len(table) == len(published)
    assert body["uk_scaling"]["gbp_per_usd_premium"] == 0.244
    assert {row["component"] for row in body["base_rate"]} >= {"base rate"}
    status, only = call(server, "/relativities?factor=region")
    assert {row["factor"] for row in only["relativities"]} == {"region"}
    assert call(server, "/relativities?factor=sex")[0] == 404


def test_monitoring_endpoint(server):
    status, body = call(server, "/monitoring")
    assert status == 200
    assert body["validation_metrics"]["test_split_2022"]["gini"] > 0.3
    overall = [r for r in body["ae"] if r["factor"] == "all" and r["period"] == "2023 out-of-time"]
    assert overall[0]["a_e"] == pytest.approx(1.0799, abs=1e-3)
    assert {r["factor"] for r in body["psi"]} >= {"age", "region"}
    status, one = call(server, "/monitoring?period=2022%20test&factor=age")
    assert {r["period"] for r in one["ae"]} == {"2022 test"}
    assert psi_empty(one)


def psi_empty(body):
    return body["psi"] == []


def test_scenario_impact_endpoint(server):
    status, zero = call(server, "/scenario-impact", {})
    assert status == 200 and zero["totals"]["change_pct"] == 0
    status, base = call(server, "/scenario-impact", {"base_change": 0.07})
    assert base["totals"]["change_pct"] == pytest.approx(7.0)
    scenario = {
        "base_change": 0.04,
        "relativity_changes": [{"factor": "age", "level": "80+", "change": 0.1}],
        "cap": 0.12,
        "floor": 0.0,
        "include_cells": True,
    }
    status, body = call(server, "/scenario-impact", scenario)
    state = service.state()
    expected = bk.apply_scenario(
        state.book,
        bk.Scenario(0.04, {("age", "80+"): 0.1}, 0.12, 0.0),
        state.tariff,
    )
    assert body["totals"]["new_premium"] == pytest.approx(expected["totals"]["new_premium"])
    assert len(body["cells"]) == len(state.book)
    assert {row["dimension"] for row in body["dislocation"]} == {
        "age group",
        "region",
        "number of conditions",
    }
    bad = {"relativity_changes": [{"factor": "age", "level": "99", "change": 0.1}]}
    assert call(server, "/scenario-impact", bad)[0] == 422
    assert call(server, "/scenario-impact", {"cap": 0.0, "floor": 0.1})[0] == 422


def test_the_saved_openapi_schema_is_current_and_lists_the_endpoints():
    assert openapi.PATH.read_text(encoding="utf-8") == openapi.schema_text()
    paths = set(json.loads(openapi.PATH.read_text(encoding="utf-8"))["paths"])
    assert paths == {"/health", "/quote", "/relativities", "/monitoring", "/scenario-impact"}


def test_the_service_imports_no_modelling_libraries():
    code = (
        "import sys, health_pricing.service.app;"
        "bad = {'statsmodels', 'duckdb', 'lightgbm', 'sklearn', 'shap', 'matplotlib'};"
        "print(sorted(bad & set(sys.modules)))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[]"


def test_predict_prices_a_golden_case_and_rejects_a_bad_profile(capsys):
    golden = golden_profiles().iloc[0]
    argv = ["--age", str(golden["age"]), "--region", golden["region"], "--json"]
    assert predict.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["premium"] == pytest.approx(golden["expected_premium_usd"])
    assert predict.main(["--age", "40", "--region", "9"]) == 2
    assert "not a level" in capsys.readouterr().err
