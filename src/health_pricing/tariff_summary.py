"""Tables and charts of the tariff summary notebook (M6, issue #69).

Everything is read from the saved tables of `outputs/v1/`, and the quotes come from the rating
engine. Nothing here fits a model. The age relativities before the monotone rule are the saved
table of `outputs/m6_draft/age_monotone_bands.csv`, because the published relativities hold the
tariff after the rule only.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from health_pricing.rating import engine  # noqa: E402

DIRECTORY = engine.OUTPUTS / "v1"
DRAFT = engine.OUTPUTS / "m6_draft"
FIGURES_DIR = DIRECTORY / "figures"
EXAMPLE_CASES = [
    "reference profile at age 40",
    "child with asthma",
    "senior with three conditions",
    "all conditions at age 55",
]
CONDITIONS = ["HIBPDX", "CHDDX", "OHRTDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX"]
BLUE, ORANGE = "#3b6ea5", "#d9822b"


def meta() -> dict:
    return json.loads((DIRECTORY / "model_version.json").read_text(encoding="utf-8"))


def _csv(name: str, **kwargs) -> pd.DataFrame:
    return pd.read_csv(DIRECTORY / name, **kwargs)


def headline_numbers() -> pd.DataFrame:
    """The numbers quoted in the notebook, with the file each is read from."""
    info = meta()
    test = info["validation_metrics"]["test_split_2022"]
    cv = info["validation_metrics"]["grouped_cross_validation_2022"]
    base = _csv("base_rate.csv").set_index("component")["value"]
    totals = _csv("scenario_example_totals.csv").iloc[0]
    scaling = info["uk_scaling"]
    MV, BR, SC, ST = (
        "model_version.json",
        "base_rate.csv",
        "scaling.json",
        "scenario_example_totals.csv",
    )
    a_e = info["validation_metrics"]["a_e_2023_after_rating_level"]
    level = info["trend_assumptions"]["rating_level_factor"]
    base22, base_now = base["base rate at 2022 level"], base["base rate"]
    factor, per_life = scaling["gbp_per_usd_premium"], scaling["gbp_per_covered_life"]
    rows = [
        ("Test deviance, 2022 split", f"{test['tweedie_deviance']:,.0f}", MV),
        ("Test Gini, 2022 split", f"{test['gini']:.3f}", MV),
        ("Out-of-fold deviance, grouped CV", f"{cv['tweedie_deviance']:,.0f}", MV),
        ("Out-of-fold Gini, grouped CV", f"{cv['gini']:.3f}", MV),
        (
            "A/E on 2023 at the rating-period level",
            f"{a_e:.3f}",
            MV,
        ),
        ("Base rate at 2022 level (dollars)", f"{base22:,.0f}", BR),
        ("Rating-period level factor", f"{level:.3f}", MV),
        ("Base rate at the rating-period level (dollars)", f"{base_now:,.0f}", BR),
        ("Scaling, pounds per dollar", f"{factor:.3f}", SC),
        ("UK claims cost per covered life (pounds)", f"{per_life}", SC),
        ("Golden cases", f"{len(_csv('golden_cases.csv'))}", "golden_cases.csv"),
        ("Example scenario, total premium change (percent)", f"{totals['change_pct']:.1f}", ST),
    ]
    return pd.DataFrame(rows, columns=["number", "value", "source"])


def relativity_table() -> pd.DataFrame:
    """The published relativities with their 95 percent bounds."""
    table = _csv("relativities.csv", dtype={"level": str})
    table["exposure"] = table["exposure"].round(0).astype(int)
    return table.round({"relativity": 3, "lower_95": 3, "upper_95": 3})


def age_before_after() -> pd.DataFrame:
    """Adult and child age relativities before and after the monotone rule, against 65-69."""
    bands = pd.read_csv(DRAFT / "age_monotone_bands.csv")
    published = _csv("relativities.csv", dtype={"level": str})
    published = published[published["factor"] == "age"].set_index("level")["relativity"]
    bands["published"] = bands["age_band"].map(published)
    return bands[["age_band", "relativity_before", "relativity_after", "published", "change_pct"]]


def age_curve_figure():
    """Age relativities before and after the rule."""
    bands = age_before_after()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(bands["age_band"], bands["relativity_before"], marker="o", color=ORANGE, label="Before")
    ax.plot(bands["age_band"], bands["relativity_after"], marker="o", color=BLUE, label="After")
    ax.set_xlabel("Age band")
    ax.set_ylabel("Relativity against the 65-69 band before the rule")
    ax.set_title("Age relativities before and after the monotone adult age rule")
    ax.tick_params(axis="x", rotation=60)
    ax.legend()
    fig.tight_layout()
    plt.close(fig)
    return fig


def example_quotes() -> dict[str, dict]:
    """Quotes from the rating engine for four golden cases, with their breakdowns."""
    golden = _csv(
        "golden_cases.csv", dtype={"region": str, **dict.fromkeys(CONDITIONS, str)}
    ).set_index("description")
    tariff = engine.load_tariff("v1")
    out = {}
    for name in EXAMPLE_CASES:
        row = golden.loc[name]
        profile = {k: row[k] for k in ["age", "region", *CONDITIONS]}
        profile["age"] = int(profile["age"])
        result = engine.rate(profile, tariff=tariff)
        result["expected_usd"] = float(row["expected_premium_usd"])
        result["profile"] = profile
        out[name] = result
    return out


def quote_summary(quotes: dict[str, dict]) -> pd.DataFrame:
    """One row per example quote, with the golden-case check."""
    rows = []
    for name, result in quotes.items():
        profile = result["profile"]
        rows.append(
            {
                "case": name,
                "age": profile["age"],
                "region": profile["region"],
                "conditions": sum(profile[c] == "1" for c in CONDITIONS),
                "premium_usd": round(result["premium"], 2),
                "risk_premium_gbp_illustrative": round(result["premium_illustrative_gbp"], 2),
                "matches_golden_case": abs(result["premium"] - result["expected_usd"]) < 1e-6,
            }
        )
    return pd.DataFrame(rows)


def breakdown(result: dict) -> pd.DataFrame:
    """The factor-by-factor breakdown of a quote, with the running premium in dollars."""
    table = result["breakdown"].copy()
    dollars = table["factor"].iloc[:-1].cumprod()  # up to the rebase, before the scaling row
    table["running_premium"] = list(dollars) + [dollars.iloc[-1] * table["factor"].iloc[-1]]
    return table.round({"factor": 4, "running_premium": 2})


def scenario_totals() -> pd.DataFrame:
    return _csv("scenario_example_totals.csv").T.rename(columns={0: "value"})


def dislocation() -> pd.DataFrame:
    table = _csv("scenario_example_dislocation.csv")
    return table.round(2)
