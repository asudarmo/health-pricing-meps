"""Stability of the relativities between 2022 and 2023 (M5, issue #45).

The final structure is refitted on all the 2023 rows, with the 2022 age knots, and its relativities
are compared with the 2022 fit. The refit is for comparison only and is never used to price. The
standard errors are the model-based ones of the M3 tables. The two fits are treated as independent,
although many people and households are in both years. A positive correlation would make the true
interval of a difference narrower, so the intervals here are somewhat wide.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.genmod import families
from statsmodels.genmod.families import links

from health_pricing.models import agecurve, factors, glm, relativities, surrogate
from health_pricing.models.outofsample import FrozenModel, OutOfTime

Z95 = relativities.Z95
KEYS = ["factor", "level"]
ALPHA = 0.05


@dataclass
class Refit:
    """The final structure fitted on 2023, next to the 2022 fit."""

    model: glm.TwoPartModel  # fitted on 2023
    tariff: surrogate.SurrogateTariff  # the surrogate model (tariff) of the 2023 fit
    balance: float  # makes 2023 predicted cost equal 2023 actual cost


def refit_2023(frozen: FrozenModel, oot: OutOfTime) -> Refit:
    """Fit the spline structure on the 2023 rows, unweighted, with the 2022 knots.

    The tariff is the surrogate model (tariff) of the 2023 fit, rebalanced on 2023.
    """
    spline = frozen.spline
    frame = oot.spline_frame
    other = [f for f in factors.FINAL_RATING if f != "age"]
    model = glm.fit_two_part(
        frame,
        "cloglog",
        ["age_group3", *other, *frozen.controls],
        name="spline 2023",
        numeric=tuple(agecurve.spline_columns(spline.df)),
    )
    entry = agecurve.AgeModel("spline 2023", model, frozen.controls, spline.knots, spline.df)
    predicted = entry.raw(frame)
    balance = factors.rebalance_factor(frame, predicted)
    tariff = surrogate.fit_surrogate_tariff(oot.frame, predicted * balance, factors.FINAL_RATING)
    return Refit(model, tariff, balance)


def _train_frame(frozen: FrozenModel) -> pd.DataFrame:
    return frozen.final_tariff.frames["spline"].train


def component_tables(
    frozen: FrozenModel, oot: OutOfTime, refit: Refit
) -> dict[str, dict[str, pd.DataFrame]]:
    """Frequency, severity and combined relativity tables of each year."""
    out = {}
    for year, model, frame in (
        ("2022", frozen.spline.model, _train_frame(frozen)),
        ("2023", refit.model, oot.spline_frame),
    ):
        frequency = relativities.component_table(model, frame, "frequency")
        severity = relativities.component_table(model, frame, "severity")
        out[year] = {
            "frequency": frequency,
            "severity": severity,
            "combined": relativities.combined_table(frequency, severity),
        }
    return out


def compare(earlier: pd.DataFrame, later: pd.DataFrame) -> pd.DataFrame:
    """Level by level ratio of the later relativity to the earlier one, with an interval.

    The interval is for the ratio of the two, from the standard errors of the logs added in
    quadrature. Reference levels have a ratio of 1 by construction and are left out. `z` is the log
    ratio over its standard error. The child bands and the adult level of `age_group3` are part of
    the age factor, so their role is `rating`.
    """
    merged = earlier.merge(later, on=KEYS, suffixes=("_2022", "_2023"), validate="one_to_one")
    merged = merged[~merged["is_reference_2022"].astype(bool)].copy()
    log_ratio = np.log(merged["relativity_2023"]) - np.log(merged["relativity_2022"])
    error = np.sqrt(merged["log_error_2022"] ** 2 + merged["log_error_2023"] ** 2)
    z = log_ratio / error.where(error > 0)
    return pd.DataFrame(
        {
            "factor": merged["factor"],
            "level": merged["level"],
            "role": np.where(merged["factor"] == "age_group3", "rating", merged["role_2022"]),
            "claimants_2022": merged["claimants_2022"],
            "claimants_2023": merged["claimants_2023"],
            "relativity_2022": merged["relativity_2022"],
            "lower_95_2022": merged["lower_95_2022"],
            "upper_95_2022": merged["upper_95_2022"],
            "relativity_2023": merged["relativity_2023"],
            "lower_95_2023": merged["lower_95_2023"],
            "upper_95_2023": merged["upper_95_2023"],
            "ratio": np.exp(log_ratio),
            "ratio_lower_95": np.exp(log_ratio - Z95 * error),
            "ratio_upper_95": np.exp(log_ratio + Z95 * error),
            "z": z,
        }
    ).reset_index(drop=True)


def comparison_tables(tables: dict[str, dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """The comparison of frequency, severity and combined relativities, stacked."""
    parts = []
    for part in ("frequency", "severity", "combined"):
        table = compare(tables["2022"][part], tables["2023"][part])
        parts.append(table.assign(part=part))
    out = pd.concat(parts, ignore_index=True)
    return out[["part", *[c for c in out.columns if c != "part"]]]


def beyond_noise(table: pd.DataFrame) -> pd.DataFrame:
    """Per part and role, the comparisons made, the ones beyond noise and the number chance gives.

    A comparison is beyond noise when the 95 percent interval of the ratio excludes 1. The
    Bonferroni count uses a threshold of 0.05 over the number of comparisons. The p-value is the
    chance of that many or more differences when the true ratios are all 1, from the binomial law.
    """
    rows = []
    for (part, role), group in table.dropna(subset=["z"]).groupby(["part", "role"]):
        n = len(group)
        flagged = int((group["z"].abs() > Z95).sum())
        bonferroni = float(stats.norm.isf(ALPHA / (2 * n)))
        rows.append(
            {
                "part": part,
                "role": role,
                "comparisons": n,
                "beyond_noise": flagged,
                "expected_by_chance": ALPHA * n,
                "p_value_that_many_by_chance": float(stats.binom.sf(flagged - 1, n, ALPHA)),
                "beyond_noise_after_bonferroni": int((group["z"].abs() > bonferroni).sum()),
                "mean_z_squared": float((group["z"] ** 2).mean()),
            }
        )
    return pd.DataFrame(rows)


def levels_beyond_noise(table: pd.DataFrame) -> pd.DataFrame:
    """The levels whose ratio interval excludes 1, largest departure first."""
    out = table[table["z"].abs() > Z95].copy()
    out["abs_z"] = out["z"].abs()
    return out.sort_values("abs_z", ascending=False).drop(columns="abs_z").reset_index(drop=True)


def _rebase_age(table: pd.DataFrame, reference: str) -> pd.DataFrame:
    """Age relativities divided by those of the adult band with the most exposure.

    The technical reference band is a child band with few claimants, so its own movement between
    the years would shift every age relativity. The rebasing changes how the table reads and not
    the model.
    """
    out = table.copy()
    is_age = out["factor"] == "age"
    scale = float(out.loc[is_age & (out["level"] == reference), "relativity"].iloc[0])
    out.loc[is_age, "relativity"] = out.loc[is_age, "relativity"] / scale
    out["is_reference"] = out["is_reference"].astype(bool)
    out.loc[is_age, "is_reference"] = out.loc[is_age, "level"] == reference
    return out


def tariff_comparison(frozen: FrozenModel, oot: OutOfTime, refit: Refit) -> pd.DataFrame:
    """Ratio of the 2023 tariff relativities to the 2022 ones, level by level.

    The tariff relativities are fitted to predictions and are point values with no interval.
    """
    reference = relativities.age_reference_for_presentation(frozen.raw)
    earlier = _rebase_age(
        relativities.tariff_table(
            frozen.final_tariff.tariff, frozen.prepared.train, factors.FINAL_RATING
        ),
        reference,
    )
    later = _rebase_age(
        relativities.tariff_table(refit.tariff, oot.frame, factors.FINAL_RATING), reference
    )
    merged = earlier.merge(later, on=KEYS, suffixes=("_2022", "_2023"), validate="one_to_one")
    merged = merged[~merged["is_reference_2022"].astype(bool)]
    return pd.DataFrame(
        {
            "factor": merged["factor"],
            "level": merged["level"],
            "claimants_2022": merged["claimants_2022"],
            "claimants_2023": merged["claimants_2023"],
            "relativity_2022": merged["relativity_2022"],
            "relativity_2023": merged["relativity_2023"],
            "ratio": merged["relativity_2023"] / merged["relativity_2022"],
        }
    ).reset_index(drop=True)


def _curve_with_interval(model: glm.TwoPartModel, knots, df: int, ages) -> pd.DataFrame:
    """The combined age relativity against age 67 with a delta-method interval on the log."""
    names = agecurve.spline_columns(df)
    ages = np.asarray(list(ages), dtype=float)
    basis = agecurve.natural_spline_basis(ages, knots)
    reference = agecurve.natural_spline_basis([agecurve.REFERENCE_AGE], knots)[0]
    direction = basis - reference
    log_value = np.zeros(len(ages))
    variance = np.zeros(len(ages))
    for part in (model.frequency, model.severity):
        beta = part.params[names].to_numpy()
        covariance = part.cov_params().loc[names, names].to_numpy()
        log_value += direction @ beta
        variance += np.einsum("ij,jk,ik->i", direction, covariance, direction)
    return pd.DataFrame({"age": ages.astype(int), "log_value": log_value, "variance": variance})


def age_curve_comparison(frozen: FrozenModel, refit: Refit) -> pd.DataFrame:
    """The combined adult age curve of each year against age 67, and their ratio with an interval.

    Both fits use the 2022 knots. The age 67 reference makes the curves comparable, and the ratio is
    the change in the shape of the curve.
    """
    spline = frozen.spline
    ages = range(agecurve.ADULT_AGE, agecurve.TOP_AGE + 1)
    earlier = _curve_with_interval(spline.model, spline.knots, spline.df, ages)
    later = _curve_with_interval(refit.model, spline.knots, spline.df, ages)
    difference = later["log_value"] - earlier["log_value"]
    error = np.sqrt(earlier["variance"] + later["variance"])
    out = pd.DataFrame({"age": earlier["age"]})
    for label, data in (("2022", earlier), ("2023", later)):
        half = Z95 * np.sqrt(data["variance"])
        out[f"relativity_{label}"] = np.exp(data["log_value"])
        out[f"lower_95_{label}"] = np.exp(data["log_value"] - half)
        out[f"upper_95_{label}"] = np.exp(data["log_value"] + half)
    out["ratio"] = np.exp(difference)
    out["ratio_lower_95"] = np.exp(difference - Z95 * error)
    out["ratio_upper_95"] = np.exp(difference + Z95 * error)
    return out


def _linear_predictor(part, matrix: pd.DataFrame) -> np.ndarray:
    columns = matrix.reindex(columns=list(part.params.index), fill_value=0.0)
    return columns.to_numpy() @ part.params.to_numpy()


def _wald(earlier, later) -> tuple[float, int]:
    """Wald statistic and degrees of freedom for equal slopes in two independent fits.

    The constant is left out, so a change of level alone does not count. The covariance of the
    difference is the sum of the two covariances.
    """
    common = [t for t in earlier.params.index if t in later.params.index and t != "const"]
    difference = (later.params[common] - earlier.params[common]).to_numpy()
    covariance = (
        earlier.cov_params().loc[common, common] + later.cov_params().loc[common, common]
    ).to_numpy()
    return float(difference @ np.linalg.pinv(covariance) @ difference), len(common)


def _level_shift(part, eta: np.ndarray, response: np.ndarray, family) -> float:
    """Multiplier on the 2022 linear predictor's scale that best fits 2023 (a constant only)."""
    fit = sm.GLM(response, np.ones((len(response), 1)), family=family, offset=eta).fit()
    return float(np.exp(fit.params[0]))


def joint_tests(frozen: FrozenModel, oot: OutOfTime, refit: Refit) -> pd.DataFrame:
    """Whether the relativities as a whole changed, apart from a shift in level.

    The test is a Wald test that every coefficient except the constant is the same in the 2022 fit
    and the 2023 refit, using the covariance of both fits. A small p-value says the relativities
    moved beyond what sampling noise explains once the level is allowed to change. The level
    shift is the constant that best fits 2023 when the 2022 linear predictor (with the fitted
    controls) is kept as an offset: a multiplier on the hazard for frequency and on the cost per
    claimant for severity.
    """
    frame = oot.spline_frame
    earlier = frozen.spline.model
    matrix = glm.design_matrix(frame, earlier.factors, rating=False, numeric=earlier.numeric)
    claimed = (frame["capped_cost"] > 0).to_numpy()
    eta_f = _linear_predictor(earlier.frequency, matrix) + np.log(frame["exposure"].to_numpy())
    eta_s = _linear_predictor(earlier.severity, matrix)[claimed]
    shifts = {
        "frequency": _level_shift(
            earlier.frequency,
            eta_f,
            claimed.astype(float),
            families.Binomial(link=links.CLogLog()),
        ),
        "severity": _level_shift(
            earlier.severity,
            eta_s,
            frame.loc[claimed, "capped_cost"].to_numpy(),
            families.Gamma(link=links.Log()),
        ),
    }
    rows = []
    for part in ("frequency", "severity"):
        statistic, df = _wald(getattr(earlier, part), getattr(refit.model, part))
        rows.append(
            {
                "part": part,
                "coefficients_compared": df,
                "wald_statistic": statistic,
                "p_value": float(stats.chi2.sf(statistic, df)),
                "level_shift": shifts[part],
            }
        )
    return pd.DataFrame(rows)
