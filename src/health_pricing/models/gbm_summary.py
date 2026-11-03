"""Headline numbers of the GBM challenger, read from the saved tables (M4-lite).

Every value is read from a table saved in `outputs/m4_draft/` by `05_gbm.ipynb` and is returned as
text as it appears in the notebooks. Nothing is refitted.
"""

from __future__ import annotations

import pandas as pd

from health_pricing.models import gbm

OUTPUT_DIR = gbm.OUTPUT_DIR
FIGURES_DIR = OUTPUT_DIR / "figures"
FIGURES = [
    ("double_lift_gbm_glm", "Double lift of the GBM against the GLM tariff"),
    ("shap_summary", "SHAP summary of the GBM"),
    ("shap_age_vs_glm", "Age effect of the GBM (SHAP) next to the GLM age curve"),
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUTPUT_DIR / name)


def _kept(share: float) -> str:
    if pd.isna(share):
        return "not defined, the GBM has no Gini advantage over the GLM tariff"
    return f"{share:.2f}"


def headline_numbers() -> pd.DataFrame:
    """The headline numbers as a table of label, text value and source file."""
    grid = read("gbm_cv_grid.csv")
    chosen = grid[grid["chosen"]].iloc[0]
    scores = read("gbm_scores_2022.csv")
    test = scores[scores["split"] == "test"].set_index("candidate")
    gaps = read("gbm_deviance_gaps.csv").set_index(["first", "second"])
    gini = read("gbm_survival.csv").set_index("measure")
    late = read("gbm_scores_2023.csv").set_index("candidate")
    names = gbm.NAMES

    def dev(key: str) -> str:
        row = test.loc[names[key]]
        reduction = f"{row['reduction_pct_dev']:.1f} percent below the baseline"
        return f"{row['tweedie_deviance']:,.0f} ({reduction})"

    gap = gaps.loc[(names["glm_tariff"], names["gbm"])]
    rows = [
        (
            "Chosen hyperparameters",
            f"learning rate {chosen['learning_rate']:.2f}, {int(chosen['num_leaves'])} leaves, "
            f"minimum {int(chosen['min_data_in_leaf'])} per leaf, {int(chosen['trees'])} trees",
            "gbm_cv_grid.csv",
        ),
        ("Combinations tried", f"{len(grid)}", "gbm_cv_grid.csv"),
        ("GBM, test deviance", dev("gbm"), "gbm_scores_2022.csv"),
        ("GBM tariff, test deviance", dev("gbm_tariff"), "gbm_scores_2022.csv"),
        ("GLM technical model, test deviance", dev("glm_technical"), "gbm_scores_2022.csv"),
        ("GLM tariff, test deviance", dev("glm_tariff"), "gbm_scores_2022.csv"),
        (
            "Test Gini: GBM, GBM tariff, GLM technical model, GLM tariff",
            ", ".join(f"{test.loc[names[k], 'gini']:.3f}" for k in names),
            "gbm_scores_2022.csv",
        ),
        (
            "Deviance gap, GLM tariff less GBM (test)",
            f"{gap['deviance_gap']:,.0f} ({gap['lower_95']:,.0f} to {gap['upper_95']:,.0f})",
            "gbm_deviance_gaps.csv",
        ),
        (
            "Share of the GBM's Gini advantage kept by its tariff",
            _kept(gini.loc["gini", "share_kept"]),
            "gbm_survival.csv",
        ),
        (
            "A/E on 2023: GBM, GBM tariff, GLM technical model, GLM tariff",
            ", ".join(f"{late.loc[names[k], 'a_e']:.3f}" for k in names),
            "gbm_scores_2023.csv",
        ),
        (
            "Gini on 2023: GBM, GBM tariff, GLM technical model, GLM tariff",
            ", ".join(f"{late.loc[names[k], 'gini']:.3f}" for k in names),
            "gbm_scores_2023.csv",
        ),
    ]
    return pd.DataFrame(rows, columns=["number", "value", "source"])
