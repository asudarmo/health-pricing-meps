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

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from health_pricing.rating import book as bk
from health_pricing.rating import engine

DESCRIPTION = (
    "UK-style private medical insurance pricing on US MEPS data. The premium is a risk premium "
    "(expected claims cost) in dollars, with illustrative pounds alongside, excluding expenses "
    "and margin. Statistical analysis only, source AHRQ MEPS."
)
app = FastAPI(title="Health pricing service", version="1.0.0", description=DESCRIPTION)


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


@app.get("/relativities", summary="The relativities, the base rate and the UK scaling")
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


@app.get("/monitoring", summary="A/E, PSI and the validation metrics of the model version")
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


@app.post("/scenario-impact", summary="Apply a rate change to the in-force book")
def scenario_impact(request: ScenarioRequest) -> dict:
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
    body = {
        "model_version": current.model_version,
        "totals": result["totals"],
        "dislocation": records(bk.dislocation(result["cells"])),
    }
    if request.include_cells:
        body["cells"] = records(result["cells"].replace({np.nan: None}))
    return body
