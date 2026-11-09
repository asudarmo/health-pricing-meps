"""The pricing web service (M10-lite).

It serves the published tables of `outputs/<model_version>/` through the rating engine and holds
no model object. Run it with `uvicorn health_pricing.service.app:app`. The environment variables
`MODEL_VERSION` (default `v1`) and `OUTPUTS_DIR` (default the repository `outputs/`) choose the
tables. Premiums are dollars per exposure-year, with a risk premium (expected claims cost) in
illustrative pounds alongside, excluding expenses and margin.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from health_pricing.rating import book as bk
from health_pricing.rating import engine, flags

DESCRIPTION = (
    "UK-style private medical insurance pricing on US MEPS data. The premium is a risk premium "
    "(expected claims cost) in dollars, with illustrative pounds alongside, excluding expenses "
    "and margin. Statistical analysis only, source AHRQ MEPS."
)
app = FastAPI(title="Health pricing service", version="1.1.0", description=DESCRIPTION)


@dataclass
class State:
    model_version: str
    directory: Path
    tariff: engine.Tariff
    book: pd.DataFrame
    meta: dict


@lru_cache(maxsize=1)
def state() -> State:
    """Read the published tables of the chosen model version once."""
    version = os.environ.get("MODEL_VERSION", "v1")
    outputs = Path(os.environ.get("OUTPUTS_DIR", engine.OUTPUTS))
    folder = outputs / version
    tariff = engine.load_tariff(version, outputs)
    keys = {key: str for key in bk.KEYS}
    in_force = pd.read_csv(folder / "in_force_book.csv", dtype=keys)
    meta = json.loads((folder / "model_version.json").read_text(encoding="utf-8"))
    return State(version, folder, tariff, in_force, meta)


def records(table: pd.DataFrame) -> list[dict]:
    """Rows as dictionaries, with missing values as null."""
    clean = table.astype(object).where(table.notna(), None)
    return clean.to_dict("records")


class Quote(BaseModel):
    """A customer profile. Unknown and not permitted fields are rejected by the rating engine."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "age": 40,
                "region": "3",
                "HIBPDX": "0",
                "CHDDX": "0",
                "OHRTDX": "0",
                "CHOLDX": "0",
                "CANCERDX": "1",
                "ARTHDX": "0",
                "ASTHDX": "0",
            }
        },
    )
    age: float = Field(description="Age in whole years, 0 to 120")
    region: str | int = Field(description="Region level, 1 to 4")
    HIBPDX: str | int | None = Field(None, description="High blood pressure, 0 or 1")
    CHDDX: str | int | None = Field(None, description="Coronary heart disease, 0 or 1")
    OHRTDX: str | int | None = Field(None, description="Other heart disease, 0 or 1")
    CHOLDX: str | int | None = Field(None, description="High cholesterol, 0 or 1")
    CANCERDX: str | int | None = Field(None, description="Cancer, 0 or 1")
    ARTHDX: str | int | None = Field(None, description="Arthritis, 0 or 1")
    ASTHDX: str | int | None = Field(None, description="Asthma, 0 or 1")
    exposure: float = Field(1.0, gt=0, description="Years of cover")


class BreakdownRow(BaseModel):
    step: str
    level: str
    factor: float


class QuoteResponse(BaseModel):
    model_version: str
    premium_usd: float
    premium_illustrative_gbp: float | None
    illustrative_label: str | None
    exposure: float
    breakdown: list[BreakdownRow]
    priced_at_reference: list[str]


class RelativityChange(BaseModel):
    factor: str
    level: str
    change: float = Field(description="Change in the relativity, 0.05 is +5 percent")


class ScenarioRequest(BaseModel):
    base_change: float = Field(0.0, description="Change to every premium, 0.04 is +4 percent")
    relativity_changes: list[RelativityChange] = []
    cap: float | None = Field(None, description="Largest increase for a cell, 0.12 is +12 percent")
    floor: float | None = Field(
        None, description="Largest decrease for a cell, -0.05 is -5 percent"
    )
    include_cells: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "base_change": 0.04,
                "relativity_changes": [{"factor": "age", "level": "80+", "change": 0.1}],
                "cap": 0.12,
                "floor": 0.0,
            }
        }
    )


class Fields(BaseModel):
    """Fields of the published tables. Others are kept, so a wider table does not break clients."""

    model_config = ConfigDict(extra="allow")


class BaseRateRow(Fields):
    component: str
    value: float


class RelativityRow(Fields):
    factor: str
    level: str
    relativity: float
    exposure: float
    lower_95: float | None = None
    upper_95: float | None = None


class RelativitiesResponse(BaseModel):
    model_version: str
    base_rate: list[BaseRateRow]
    uk_scaling: dict[str, Any] | None
    relativities: list[RelativityRow]


class AERow(Fields):
    factor: str
    level: str
    segment: str
    period: str
    actual: float
    expected: float
    exposure: float
    a_e: float


class PSIRow(Fields):
    factor: str
    period: str
    psi: float | None


class MonitoringResponse(BaseModel):
    model_version: str
    validation_metrics: dict[str, Any]
    ae: list[AERow]
    psi: list[PSIRow]


class Totals(Fields):
    exposure: float
    old_premium: float
    new_premium: float
    change_pct: float
    cap_floor_cost: float
    cells_capped: int
    cells_floored: int
    exposure_capped: float = Field(description="Life-years in the cells above the cap")
    exposure_floored: float = Field(description="Life-years in the cells below the floor")
    old_premium_gbp: float | None = None
    new_premium_gbp: float | None = None


class DislocationRow(Fields):
    dimension: str
    segment: str
    exposure: float
    mean_change_pct: float
    p05_change_pct: float
    p25_change_pct: float
    p50_change_pct: float
    p75_change_pct: float
    p95_change_pct: float
    share_increase_over_10pct: float


class HistogramBucket(BaseModel):
    bucket_low: float | None = Field(description="Percent change, included. Null is open below")
    bucket_high: float | None = Field(description="Percent change, excluded. Null is open above")
    exposure: float = Field(description="Life-years")


class ScenarioResponse(BaseModel):
    model_version: str
    totals: Totals
    dislocation: list[DislocationRow]
    histogram: list[HistogramBucket]
    histogram_edges_pct: list[float] = Field(
        description="The fixed bucket edges in percent. Buckets are [low, high)"
    )
    projected_ae: float | None = Field(
        description="Actual / (expected x new premium / old premium) on the latest A/E period"
    )
    cells: list[dict[str, Any]] | None = None


class FactorLevel(BaseModel):
    level: str
    label: str


class RatingFactor(BaseModel):
    factor: str
    label: str
    levels: list[FactorLevel]


class DataYears(BaseModel):
    fit: int
    out_of_time: int
    cost_basis: str


class TrendAssumptions(Fields):
    forecast_trend: float
    rebase: float


class HeadlineAE(BaseModel):
    period: str
    a_e: float
    lower_95: float | None
    upper_95: float | None
    exposure: float


class RecalibrationFlag(BaseModel):
    segment: str
    a_e: float
    exposure: float
    gap_type: Literal["level shift", "change in shape"]
    note: str


class ModelResponse(BaseModel):
    id: str
    date: str
    description: str
    data_years: DataYears
    trend_assumptions: TrendAssumptions
    permitted_rating_factors: list[RatingFactor]
    headline_ae: HeadlineAE
    recalibration_flags: list[RecalibrationFlag]


@app.get("/health", summary="Service and model version status")
def health() -> dict:
    current = state()
    return {
        "status": "ok",
        "model_version": current.model_version,
        "date": current.meta["date"],
        "description": current.meta["description"],
        "golden_cases_status": current.meta["golden_cases"]["status"],
    }


@app.post("/quote", response_model=QuoteResponse, summary="Price a profile with its breakdown")
def quote(request: Quote) -> QuoteResponse:
    current = state()
    profile = request.model_dump(exclude_none=True, exclude={"exposure"})
    try:
        result = engine.rate(profile, tariff=current.tariff, exposure=request.exposure)
    except engine.ProfileError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return QuoteResponse(
        model_version=current.model_version,
        premium_usd=result["premium"],
        premium_illustrative_gbp=result.get("premium_illustrative_gbp"),
        illustrative_label=result.get("illustrative_label"),
        exposure=result["exposure"],
        breakdown=records(result["breakdown"]),
        priced_at_reference=result["priced_at_reference"],
    )


@app.get(
    "/relativities",
    response_model=RelativitiesResponse,
    response_model_exclude_unset=True,
    summary="The relativities, the base rate and the UK scaling",
)
def relativities(factor: str | None = Query(None, description="Only this factor")) -> dict:
    current = state()
    table = current.tariff.relativities[engine_columns()]
    if factor is not None:
        table = table[table["factor"] == factor]
        if table.empty:
            raise HTTPException(status_code=404, detail=f"No factor '{factor}'")
    base = pd.read_csv(current.directory / engine.BASE_RATE)
    return {
        "model_version": current.model_version,
        "base_rate": records(base),
        "uk_scaling": current.tariff.scaling,
        "relativities": records(table),
    }


def engine_columns() -> list[str]:
    return ["factor", "level", "relativity", "exposure", "lower_95", "upper_95"]


@app.get(
    "/monitoring",
    response_model=MonitoringResponse,
    response_model_exclude_unset=True,
    summary="A/E, PSI and the validation metrics of the model version",
)
def monitoring(
    period: str | None = Query(None, description="Only this A/E or PSI period"),
    factor: str | None = Query(None, description="Only this factor"),
) -> dict:
    current = state()
    ae = pd.read_csv(current.directory / "ae_table.csv", dtype={"level": str})
    psi = pd.read_csv(current.directory / "psi_table.csv")
    for name in ("period", "factor"):
        value = {"period": period, "factor": factor}[name]
        if value is not None:
            ae, psi = ae[ae[name] == value], psi[psi[name] == value]
    ae = ae.assign(a_e=ae["actual"] / ae["expected"])
    return {
        "model_version": current.model_version,
        "validation_metrics": current.meta["validation_metrics"],
        "ae": records(ae),
        "psi": records(psi),
    }


PERIOD = "2023 out-of-time"
HISTOGRAM_EDGES_PCT = [-20.0, -10.0, -5.0, -2.5, 0.0, 2.5, 5.0, 10.0, 15.0, 20.0, 30.0]


def histogram(cells: pd.DataFrame) -> list[dict]:
    """Exposure by bucket of individual premium change, buckets [low, high) with open ends."""
    edges = HISTOGRAM_EDGES_PCT
    index = np.searchsorted(edges, cells["change_pct"].to_numpy(), side="right")
    exposure = np.bincount(index, weights=cells["exposure"].to_numpy(), minlength=len(edges) + 1)
    lows, highs = [None, *edges], [*edges, None]
    return [
        {"bucket_low": lo, "bucket_high": hi, "exposure": float(x)}
        for lo, hi, x in zip(lows, highs, exposure)
    ]


def overall_ae(current: State) -> pd.Series:
    """The `all` row of the latest A/E period."""
    table = pd.read_csv(current.directory / "ae_table.csv", dtype={"level": str})
    return table[(table["factor"] == "all") & (table["period"] == PERIOD)].iloc[0]


@app.post(
    "/scenario-impact",
    response_model=ScenarioResponse,
    response_model_exclude_unset=True,
    summary="Apply a rate change to the in-force book",
)
def scenario_impact(request: ScenarioRequest) -> dict:
    """Old and new premium for the in-force book under a rate change.

    `projected_ae` is actual divided by expected after the change. Actual and expected are the
    totals of the latest A/E period (`2023 out-of-time`, the `all` row of `ae_table.csv`), and
    expected after the change is expected times new premium over old premium of the book.
    `exposure_capped` and `exposure_floored` are the life-years in the `cells_capped` and
    `cells_floored` cells. The histogram counts life-years by individual premium change.
    """
    current = state()
    if request.cap is not None and request.floor is not None and request.cap < request.floor:
        raise HTTPException(status_code=422, detail="cap must not be below floor")
    known = set(zip(current.tariff.relativities["factor"], current.tariff.relativities["level"]))
    changes = {}
    for item in request.relativity_changes:
        if (item.factor, item.level) not in known:
            raise HTTPException(
                status_code=422, detail=f"No level '{item.level}' for factor '{item.factor}'"
            )
        changes[(item.factor, item.level)] = item.change
    scenario = bk.Scenario(request.base_change, changes, request.cap, request.floor)
    result = bk.apply_scenario(current.book, scenario, current.tariff)
    cells = result["cells"]
    uncapped = cells["uncapped_change_pct"] / 100
    capped = uncapped > (request.cap if request.cap is not None else np.inf)
    floored = uncapped < (request.floor if request.floor is not None else -np.inf)
    totals = {
        **result["totals"],
        "exposure_capped": float(cells.loc[capped, "exposure"].sum()),
        "exposure_floored": float(cells.loc[floored, "exposure"].sum()),
    }
    ae = overall_ae(current)
    ratio = totals["new_premium"] / totals["old_premium"]
    body = {
        "model_version": current.model_version,
        "totals": totals,
        "dislocation": records(bk.dislocation(cells)),
        "histogram": histogram(cells),
        "histogram_edges_pct": HISTOGRAM_EDGES_PCT,
        "projected_ae": float(ae["actual"] / (ae["expected"] * ratio)),
    }
    if request.include_cells:
        body["cells"] = records(cells.replace({np.nan: None}))
    return body


FACTOR_LABELS = {
    "age": "Age band",
    "region": "Region",
    "HIBPDX": "High blood pressure",
    "CHDDX": "Coronary heart disease",
    "OHRTDX": "Other heart disease",
    "CHOLDX": "High cholesterol",
    "CANCERDX": "Cancer",
    "ARTHDX": "Arthritis",
    "ASTHDX": "Asthma",
}
REGION_LABELS = {"1": "Northeast", "2": "Midwest", "3": "South", "4": "West"}


def level_label(factor: str, level: str) -> str:
    if factor == "region":
        return REGION_LABELS.get(level, level)
    if factor == "age":
        return level
    return {"0": "No", "1": "Yes"}.get(level, level)


@app.get("/model", response_model=ModelResponse, summary="The model version and its status")
def model() -> dict:
    """The version facts, the permitted factors, the headline A/E and the recalibration flags.

    The flags apply the rule of `_docs/recalibration-rule.md` to `ae_intervals.csv`, level by level
    (see `health_pricing.rating.flags`).
    """
    current = state()
    meta = current.meta
    table = current.tariff.relativities
    factors = []
    for factor in meta["permitted_rating_factors"]:
        levels = [str(x) for x in table.loc[table["factor"] == factor, "level"]]
        factors.append(
            {
                "factor": factor,
                "label": FACTOR_LABELS.get(factor, factor),
                "levels": [{"level": x, "label": level_label(factor, x)} for x in levels],
            }
        )
    intervals = pd.read_csv(current.directory / "ae_intervals.csv", dtype={"level": str})
    total = intervals[intervals["factor"] == "all"].iloc[0]
    return {
        "id": meta["id"],
        "date": meta["date"],
        "description": meta["description"],
        "data_years": meta["data_years"],
        "trend_assumptions": meta["trend_assumptions"],
        "permitted_rating_factors": factors,
        "headline_ae": {
            "period": str(total["period"]),
            "a_e": float(total["a_e"]),
            "lower_95": float(total["lower_95"]),
            "upper_95": float(total["upper_95"]),
            "exposure": float(total["exposure"]),
        },
        "recalibration_flags": flags.segment_flags(intervals),
    }
