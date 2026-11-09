"""Publish `outputs/<version>/`, the contract of `_docs/plan.md` section 6 (M6, issue #62).

Run `python -m health_pricing.publish`. The version holds aggregated tables only:
`model_version.json`, `relativities.csv`, `base_rate.csv`, `scaling.json`, `ae_table.csv`,
`psi_table.csv`, `in_force_book.csv`, `golden_cases.csv`, the example scenario tables and the
dislocation histogram. The golden cases come from the rating engine and are a regression
baseline until the Excel reconciliation of M7 replaces them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from health_pricing.models import agemonotone, finaltariff, metrics, outofsample
from health_pricing.rating import book as bk
from health_pricing.rating import engine

VERSION = "v1"
GOLDEN_LABEL = "regression baseline, provisional until the Excel reconciliation"
PERMITTED = ["age", "region", *finaltariff.CONDITIONS]
RELATIVITY_COLUMNS = ["factor", "level", "relativity", "exposure", "lower_95", "upper_95"]
AE_COLUMNS = ["factor", "level", "segment", "period", "actual", "expected", "exposure"]
PERIOD_2022 = "2022 test"
PERIOD_2023 = "2023 out-of-time"
UK_SCALING = {
    "gbp_per_usd_premium": 0.244,
    "label": engine.GBP_LABEL,
    "basis": "UK PMI claims paid per covered life, all covered lives, 2023",
    "claims_paid_gbp": 3.57e9,
    "people_covered": 6.2e6,
    "gbp_per_covered_life": 576,
    "model_mean_usd_rating_level": 2358,
    "includes_exchange_rate": True,
    "source": (
        "ABI press release, 6 November 2024, private medical insurance data for 2023 "
        "(https://www.abi.org.uk/media-hub/news-post/"
        "private-medical-insurers-report-record-47-million-covered-by-employer-health-schemes)"
    ),
    "decided": "2026-11-05, gate 8, option A",
    "illustrative": True,
}


def ae_table(frozen, adjusted, oot) -> pd.DataFrame:
    """A/E of the final tariff by rating factor level, for the 2022 test split and 2023."""
    level = finaltariff.RATING_LEVEL
    parts = []
    for period, frame, predicted in (
        (PERIOD_2022, frozen.prepared.test, adjusted.predict(frozen.prepared.test)),
        (PERIOD_2023, oot.frame, adjusted.predict(oot.frame) * level),
    ):
        table = metrics.ae_by_factor(frame, predicted, PERMITTED)
        table["segment"], table["period"] = "all", period
        overall = pd.DataFrame(
            [
                {
                    "factor": "all",
                    "level": "all",
                    "segment": "all",
                    "period": period,
                    "actual": frame["cost"].sum(),
                    "expected": float(np.sum(predicted)),
                    "exposure": frame["exposure"].sum(),
                }
            ]
        )
        parts += [table, overall]
    return pd.concat(parts, ignore_index=True)[AE_COLUMNS]


def ae_intervals(
    directory: Path = outofsample.OUTPUT_DIR, version: Path | None = None
) -> pd.DataFrame:
    """The 2023 A/E of each rating level with its interval, on the published `ae_table` basis.

    The intervals come from the out-of-time test of the tariff. They are scaled by the ratio of the
    published A/E (which includes the rating level) to the test A/E, so each interval keeps its
    relative width. Read by `health_pricing.rating.flags.segment_flags`.
    """
    published = pd.read_csv(
        version or engine.OUTPUTS / VERSION / "ae_table.csv", dtype={"level": str}
    )
    published = published[published["period"] == PERIOD_2023].copy()
    published["a_e"] = published["actual"] / published["expected"]
    overall = published.loc[published["factor"] == "all", "a_e"].iloc[0]
    test = pd.read_csv(directory / "ae_by_level_2023.csv", dtype={"level": str})
    test = test[(test["model"] == outofsample.TARIFF) & (test["role"] == "rating")]
    test = test.rename(columns=lambda c: f"test_{c}" if c not in ("factor", "level") else c)
    total = (
        pd.read_csv(directory / "ae_overall_2023.csv").set_index("model").loc[outofsample.TARIFF]
    )
    total_row = pd.DataFrame(
        [
            {
                "factor": "all",
                "level": "all",
                "test_a_e": total["a_e"],
                "test_lower_95": total["lower_95"],
                "test_upper_95": total["upper_95"],
                "test_relative_a_e": 1.0,
                "test_relative_lower_95": 1.0,
                "test_relative_upper_95": 1.0,
                "test_claimants": test.groupby("factor")["test_claimants"].sum().max(),
                "test_enough_claimants": True,
            }
        ]
    )
    merged = published.merge(pd.concat([test, total_row]), on=["factor", "level"], how="inner")
    scale = merged["a_e"] / merged["test_a_e"]
    relative = merged["a_e"] / overall
    relative_scale = relative / merged["test_relative_a_e"]
    return pd.DataFrame(
        {
            "factor": merged["factor"],
            "level": merged["level"],
            "period": PERIOD_2023,
            "a_e": merged["a_e"],
            "lower_95": merged["test_lower_95"] * scale,
            "upper_95": merged["test_upper_95"] * scale,
            "relative_a_e": relative,
            "relative_lower_95": merged["test_relative_lower_95"] * relative_scale,
            "relative_upper_95": merged["test_relative_upper_95"] * relative_scale,
            "claimants": merged["test_claimants"].astype(int),
            "enough_claimants": merged["test_enough_claimants"].astype(bool),
            "exposure": merged["exposure"],
        }
    )


def psi_table(directory: Path = outofsample.OUTPUT_DIR) -> pd.DataFrame:
    """PSI of the rating factors, 2023 against 2022 train, from the M5 table.

    Factor mixes do not depend on the age rule, so the M5 values stand. The predicted cost
    row is that of the tariff of M3 and is not recomputed for the adjusted tariff.
    """
    table = pd.read_csv(directory / "drift_psi_factors.csv")
    table = table[table["kind"] == "rating"].rename(columns={"measure": "factor"})
    table["period"] = "2023 vs 2022 train"
    return table[["factor", "period", "psi"]].reset_index(drop=True)


def golden_cases(tariff: engine.Tariff) -> pd.DataFrame:
    """Profiles with their expected premiums, from the rating engine."""
    none = dict.fromkeys(finaltariff.CONDITIONS, "0")
    profiles = [("reference profile at age 40", {"age": 40, "region": "3", **none})]
    for low, _, label in tariff.age_bands:
        profiles.append((f"age band {label}", {"age": low, "region": "3", **none}))
    for region in tariff.levels("region"):
        profiles.append((f"region {region}", {"age": 40, "region": region, **none}))
    for condition in finaltariff.CONDITIONS:
        profiles.append(
            (f"{condition} only", {"age": 40, "region": "3", **{**none, condition: "1"}})
        )
    profiles += [
        ("child with asthma", {"age": 8, "region": "1", **{**none, "ASTHDX": "1"}}),
        (
            "senior with three conditions",
            {"age": 72, "region": "2", **{**none, "CHDDX": "1", "ARTHDX": "1", "HIBPDX": "1"}},
        ),
        ("oldest age", {"age": 95, "region": "4", **{**none, "CANCERDX": "1"}}),
        ("all conditions at age 55", {"age": 55, "region": "3", **dict.fromkeys(none, "1")}),
        ("young adult in region 4", {"age": 22, "region": "4", **none}),
    ]
    rows = []
    for number, (description, profile) in enumerate(profiles, start=1):
        result = engine.rate(profile, tariff=tariff)
        row = {"case_id": f"G{number:02d}", "description": description, **profile}
        row["expected_premium_usd"] = result["premium"]
        row["expected_premium_gbp"] = result.get("premium_illustrative_gbp", np.nan)
        row["status"] = GOLDEN_LABEL
        rows.append(row)
    return pd.DataFrame(rows)


def model_version(frozen, adjusted, cv, tariff_scores, ae: pd.DataFrame) -> dict:
    """The metadata of the version."""
    test = tariff_scores[tariff_scores["split"] == "test"].set_index("candidate")
    final = test.loc[agemonotone.ADJUSTED]
    oot_all = ae[(ae["factor"] == "all") & (ae["period"] == PERIOD_2023)].iloc[0]
    return {
        "id": VERSION,
        "date": date.today().isoformat(),
        "description": "v1: 2022-fitted multiplicative tariff with a monotone adult age rule",
        "data_years": {"fit": 2022, "out_of_time": 2023, "cost_basis": "2023 prices, PMI scope"},
        "trend_assumptions": {
            "forecast_trend": finaltariff.FORECAST_TREND,
            "forecast_trend_range": [1.008, 1.031],
            "rebase": finaltariff.DECIDED_REBASE,
            "rebase_range": [1.025, 1.145],
            "rating_level_factor": finaltariff.RATING_LEVEL,
            "note": "v2 refits on pooled years and projects to a rating period",
        },
        "validation_metrics": {
            "test_split_2022": {
                "tweedie_deviance": float(final["tweedie_deviance"]),
                "gini": float(final["gini"]),
                "a_e": float(final["a_e"]),
            },
            "grouped_cross_validation_2022": {
                "tweedie_deviance": float(
                    cv.scores.set_index("candidate").loc[agemonotone.ADJUSTED, "tweedie_deviance"]
                ),
                "gini": float(cv.scores.set_index("candidate").loc[agemonotone.ADJUSTED, "gini"]),
            },
            "a_e_2023_after_rating_level": float(oot_all["actual"] / oot_all["expected"]),
        },
        "permitted_rating_factors": PERMITTED,
        "excluded_factors": sorted(engine.NOT_PERMITTED),
        "analysis_only_priced_at_reference": sorted(engine.ANALYSIS_ONLY),
        "uk_scaling": UK_SCALING,
        "golden_cases": {"file": "golden_cases.csv", "status": GOLDEN_LABEL},
        "monetary_unit": "dollars per exposure-year at 2023 prices, with a risk premium in "
        "illustrative pounds alongside",
    }


def publish(version: str = VERSION) -> Path:
    """Build every file of the contract under `outputs/<version>/`."""
    directory = engine.OUTPUTS / version
    (directory / "figures").mkdir(parents=True, exist_ok=True)
    frozen = outofsample.freeze()
    adjusted = agemonotone.adjust(frozen)
    oot = outofsample.load_out_of_time(frozen)

    relativities = finaltariff.relativity_table(frozen, adjusted)[RELATIVITY_COLUMNS]
    relativities.to_csv(directory / engine.RELATIVITIES, index=False)
    finaltariff.base_rate_table(frozen, adjusted).to_csv(directory / engine.BASE_RATE, index=False)
    (directory / engine.SCALING).write_text(json.dumps(UK_SCALING, indent=2), encoding="utf-8")

    tariff = engine.load_tariff(version)
    ae = ae_table(frozen, adjusted, oot)
    ae.to_csv(directory / "ae_table.csv", index=False)
    psi_table().to_csv(directory / "psi_table.csv", index=False)
    golden_cases(tariff).to_csv(directory / "golden_cases.csv", index=False)

    in_force = bk.build_book(pd.concat([frozen.prepared.train, frozen.prepared.test]))
    in_force.to_csv(directory / "in_force_book.csv", index=False)
    result = bk.apply_scenario(in_force, bk.EXAMPLE, tariff)
    result["cells"].to_csv(directory / "scenario_example_cells.csv", index=False)
    pd.DataFrame([result["totals"]]).to_csv(directory / "scenario_example_totals.csv", index=False)
    bk.dislocation(result["cells"]).to_csv(
        directory / "scenario_example_dislocation.csv", index=False
    )
    bk.save_histogram(result["cells"], directory / "figures" / "scenario_example_dislocation.png")

    cv = agemonotone.cross_validate(frozen)
    scores = agemonotone.score_table(frozen, adjusted)
    meta = model_version(frozen, adjusted, cv, scores, ae)
    (directory / "model_version.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return directory


if __name__ == "__main__":
    print(publish())
