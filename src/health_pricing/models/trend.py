"""The frequency trend and the decomposition of the 2023 gap (M5, issue #43, gate 4 part 2).

The forecast trend for the out-of-time test is set without looking at 2023. A trend is a factor
on the claim hazard, so a person-year's chance of a claim becomes `1 - (1 - p)^f`, where `p` is
the chance without a trend, and the claim probability stays below 1. The trend that the 2022 to
2023 data imply is a diagnostic only and is never used as a forecast, because that would make the
2023 A/E close to 1 by construction.

The 2023 gap in cost per exposure year is split exactly, as a product, into four parts.

- **Mix** is the change in the model's expected cost per exposure year, from the people covered.
- **Frequency** is the change in actual claimants over the model's expected claimants.
- **Severity beyond the price index** is the change in actual capped cost per claimant over the
  model's expected cost per claimant. 2022 costs are already on 2023 prices.
- **Large claims** is the change in the share of cost above the cap.

All ratios are of 2023 to 2022 train. Intervals resample households within each period.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from health_pricing.models import factors, large_claims, smoking
from health_pricing.models.outofsample import FrozenModel, OutOfTime

SEED = 20231102
N_BOOT = 2000
SUM_COLUMNS = ["t", "N", "S", "Y", "p", "pm"]
AGE_GROUPS = ["Children", "18-39", "40-64", "65+"]


@dataclass
class Parts:
    """Row-level pieces of a period: exposure, claimants, costs and the model's p and mu."""

    frame: pd.DataFrame
    t: np.ndarray
    N: np.ndarray
    S: np.ndarray
    Y: np.ndarray
    p: np.ndarray  # chance of a claim without a trend
    mu: np.ndarray  # expected capped cost of a claimant
    households: np.ndarray

    @property
    def pm(self) -> np.ndarray:
        return self.p * self.mu


def parts(frozen: FrozenModel, spline_frame: pd.DataFrame) -> Parts:
    """The row-level pieces for a frame with the spline terms, with controls at the reference."""
    priced = factors.at_reference(spline_frame, frozen.controls)
    model = frozen.spline.model
    return Parts(
        frame=spline_frame,
        t=spline_frame["exposure"].to_numpy(dtype=float),
        N=(spline_frame["capped_cost"] > 0).to_numpy(dtype=float),
        S=spline_frame["capped_cost"].to_numpy(dtype=float),
        Y=spline_frame["cost"].to_numpy(dtype=float),
        p=np.asarray(model.expected_claimants(priced)),
        mu=np.asarray(model.expected_severity(priced)),
        households=pd.factorize(spline_frame["DUID"])[0],
    )


def train_parts(frozen: FrozenModel) -> Parts:
    return parts(frozen, frozen.final_tariff.frames["spline"].train)


def out_of_time_parts(frozen: FrozenModel, oot: OutOfTime) -> Parts:
    return parts(frozen, oot.spline_frame)


def hazard_trend(p: np.ndarray, factor: float) -> np.ndarray:
    """The chance of a claim after a trend of `factor` on the claim hazard."""
    return 1 - (1 - p) ** factor


def technical_prediction(frozen: FrozenModel, pieces: Parts, factor: float = 1.0) -> np.ndarray:
    """Technical model cost with a trend on the claim hazard, with the load and the rebalancing."""
    load = 1 + large_claims.PROVISIONAL_LOAD
    return frozen.balance * load * hazard_trend(pieces.p, factor) * pieces.mu


def level_equivalent(frozen: FrozenModel, pieces: Parts, factor: float) -> float:
    """The average rise in the technical model's cost from a hazard factor.

    A hazard factor raises a claim probability by less than the factor when the probability is
    high, so the rise in cost is smaller than the factor. The tariff is a level charge, and it
    carries the same trend as the technical model by this average rise.
    """
    return float(
        technical_prediction(frozen, pieces, factor).sum()
        / technical_prediction(frozen, pieces).sum()
    )


def tariff_prediction(
    frozen: FrozenModel, frame: pd.DataFrame, pieces: Parts, factor: float = 1.0
) -> np.ndarray:
    """Tariff cost with the trend applied as a level factor, equal to the technical model's rise."""
    return frozen.tariff(frame) * level_equivalent(frozen, pieces, factor)


def implied_hazard_factor(train: Parts, later: Parts) -> float:
    """The hazard factor that makes the model's expected claimants match the claimants of `later`.

    The model's expected claimants over actual claimants on 2022 train is the calibration of the
    frequency part, so the target is the actual claimants of `later` times that calibration. This is
    the trend that the data imply, which is a diagnostic and never a forecast.
    """
    calibration = train.p.sum() / train.N.sum()
    target = later.N.sum() * calibration
    return float(brentq(lambda f: hazard_trend(later.p, f).sum() - target, 0.5, 2.0))


def household_sums(pieces: Parts, columns: dict[str, np.ndarray]) -> np.ndarray:
    """Household by column sums, the input of the bootstrap."""
    count = pieces.households.max() + 1
    out = np.zeros((count, len(columns)))
    for k, values in enumerate(columns.values()):
        out[:, k] = np.bincount(pieces.households, weights=values, minlength=count)
    return out


def resampled_sums(matrix: np.ndarray, n_boot: int, seed: int) -> np.ndarray:
    """Column sums of `n_boot` household resamples with replacement."""
    count = matrix.shape[0]
    draws = np.random.default_rng(seed).multinomial(count, np.full(count, 1 / count), n_boot)
    return draws @ matrix


def _statistics(sums: np.ndarray) -> dict[str, np.ndarray]:
    t, n, s, y, p, pm = (sums[..., k] for k in range(6))
    return {
        "mix": pm / t,
        "frequency": n / p,
        "severity": (s / n) / (pm / p),
        "large_claims": y / s,
        "cost_per_exposure_year": y / t,
    }


def _base_columns(pieces: Parts) -> dict[str, np.ndarray]:
    return {
        "t": pieces.t,
        "N": pieces.N,
        "S": pieces.S,
        "Y": pieces.Y,
        "p": pieces.p,
        "pm": pieces.pm,
    }


def decomposition(
    train: Parts, later: Parts, n_boot: int = N_BOOT, seed: int = SEED
) -> pd.DataFrame:
    """The ratio of 2023 to 2022 train in cost per exposure year, split into four parts.

    The four ratios multiply to the total ratio exactly. Each has a 95 percent interval from
    resampling the households of both periods.
    """
    base = _base_columns(train)
    other = _base_columns(later)
    point = {
        name: _statistics(np.array([[arr.sum() for arr in other.values()]]))[name][0]
        / _statistics(np.array([[arr.sum() for arr in base.values()]]))[name][0]
        for name in ("mix", "frequency", "severity", "large_claims", "cost_per_exposure_year")
    }
    first = _statistics(resampled_sums(household_sums(train, base), n_boot, seed))
    second = _statistics(resampled_sums(household_sums(later, other), n_boot, seed + 1))
    rows = []
    treatment = {
        "mix": "Not a level change. The rating structure prices the mix.",
        "frequency": "A level change if it persists. It is a trend on the base rate.",
        "severity": "A level change if it persists. It is a trend on the base rate.",
        "large_claims": "Not a level change. The large-claim load covers it.",
        "cost_per_exposure_year": "The total gap. The level change is frequency and severity.",
    }
    labels = {
        "mix": "Mix of people (modelled factors)",
        "frequency": "Frequency (actual over expected claimants)",
        "severity": "Severity beyond the price index",
        "large_claims": "Large-claim contribution",
        "cost_per_exposure_year": "Total, cost per exposure year",
    }
    for name in ("mix", "frequency", "severity", "large_claims", "cost_per_exposure_year"):
        ratio = second[name] / first[name]
        rows.append(
            {
                "component": labels[name],
                "ratio": point[name],
                "change_percent": 100 * (point[name] - 1),
                "lower_95_percent": 100 * (np.quantile(ratio, 0.025) - 1),
                "upper_95_percent": 100 * (np.quantile(ratio, 0.975) - 1),
                "share_of_log_gap": np.log(point[name]) / np.log(point["cost_per_exposure_year"]),
                "pricing_treatment": treatment[name],
            }
        )
    return pd.DataFrame(rows)


def load_check(frozen: FrozenModel, later: Parts, own_excess_load: float) -> dict[str, float]:
    """How much of the A/E is consistent with the provisional large-claim load.

    With the load set to the 2023 excess over the cap, the prediction is scaled by the ratio of the
    two loads. The change in A/E is the part of the gap that the load can explain. A load that is
    already high enough leaves the gap unchanged or wider. Nothing is tuned.
    """
    prediction = technical_prediction(frozen, later)
    a_e = later.Y.sum() / prediction.sum()
    ratio = (1 + own_excess_load) / (1 + large_claims.PROVISIONAL_LOAD)
    return {
        "a_e_provisional_load": a_e,
        "own_excess_load": own_excess_load,
        "provisional_load": large_claims.PROVISIONAL_LOAD,
        "a_e_if_load_matched": a_e / ratio,
        "change_in_a_e_points": 100 * (a_e / ratio - a_e),
    }


def trend_options(
    frozen: FrozenModel,
    oot: OutOfTime,
    options: dict[str, tuple[float, str, str]],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> pd.DataFrame:
    """A/E on 2023 for the technical model and the tariff under each trend option.

    `options` maps a label to a hazard factor, the source and how the option is used. The interval
    is
    from resampling the 2023 households.
    """
    later = out_of_time_parts(frozen, oot)
    columns = {"Y": later.Y}
    for k, (factor, _, _) in enumerate(options.values()):
        columns[f"tech_{k}"] = technical_prediction(frozen, later, factor)
        columns[f"tariff_{k}"] = tariff_prediction(frozen, oot.frame, later, factor)
    sums = household_sums(later, columns)
    boot = resampled_sums(sums, n_boot, seed)
    rows = []
    for k, (label, (factor, source, use)) in enumerate(options.items()):
        row = {"option": label, "hazard_factor": factor, "trend_percent": 100 * (factor - 1)}
        for model, key in (("technical", "tech"), ("tariff", "tariff")):
            column = list(columns).index(f"{key}_{k}")
            estimate = sums[:, 0].sum() / sums[:, column].sum()
            draws = boot[:, 0] / boot[:, column]
            row[f"{model}_a_e"] = estimate
            row[f"{model}_lower_95"] = float(np.quantile(draws, 0.025))
            row[f"{model}_upper_95"] = float(np.quantile(draws, 0.975))
        row["source"] = source
        row["use"] = use
        rows.append(row)
    return pd.DataFrame(rows)


def age_group(frame: pd.DataFrame) -> pd.Series:
    """Children, and the three broad adult groups, from the age band of each row."""
    bands = frame["age"].astype(object)
    group = bands.map(smoking.broad_group)
    child = bands.map(smoking.band_start) < 18
    return group.where(~child, "Children")


def frequency_table(
    frozen: FrozenModel, oot: OutOfTime, n_boot: int = N_BOOT, seed: int = SEED
) -> pd.DataFrame:
    """Claimant rate and claims per exposure year in 2022 and 2023, overall and by age group.

    `claimant_rate` is the share of person-years with a claim and `claims_per_exposure_year` is the
    number of claims over exposure. The ratio of 2023 to 2022 train has a household interval. The
    mix-adjusted ratio is the change in actual over expected claimants, so a change in the mix of
    people is not read as a trend.
    """
    periods = {
        "2022 train": train_parts(frozen),
        "2022 test": parts(frozen, frozen.final_tariff.frames["spline"].test),
        "2023": out_of_time_parts(frozen, oot),
    }
    rows = []
    for group in ["All", *AGE_GROUPS]:
        masks = {
            name: (
                np.ones(len(piece.t), dtype=bool)
                if group == "All"
                else (age_group(piece.frame) == group).to_numpy()
            )
            for name, piece in periods.items()
        }
        stats = {}
        for name, piece in periods.items():
            keep = masks[name]
            claims = piece.frame["claim_count"].to_numpy(dtype=float)
            stats[name] = {
                "person_years": int(keep.sum()),
                "exposure": piece.t[keep].sum(),
                "claimant_rate": piece.N[keep].mean(),
                "claims_per_exposure_year": claims[keep].sum() / piece.t[keep].sum(),
                "actual_over_expected": piece.N[keep].sum() / piece.p[keep].sum(),
            }
        boot = {}
        for k, name in enumerate(("2022 train", "2023")):
            piece = periods[name]
            keep = masks[name]
            claims = piece.frame["claim_count"].to_numpy(dtype=float)
            matrix = household_sums(
                piece,
                {
                    "keep": keep.astype(float),
                    "N": piece.N * keep,
                    "claims": claims * keep,
                    "t": piece.t * keep,
                    "p": piece.p * keep,
                },
            )
            sums = resampled_sums(matrix, n_boot, seed + k)
            boot[name] = {
                "claimant_rate": sums[:, 1] / sums[:, 0],
                "claims_per_exposure_year": sums[:, 2] / sums[:, 3],
                "actual_over_expected": sums[:, 1] / sums[:, 4],
            }
        for name in periods:
            row = {"group": group, "period": name, **stats[name]}
            for measure in ("claimant_rate", "claims_per_exposure_year", "actual_over_expected"):
                if name == "2023":
                    ratio = stats["2023"][measure] / stats["2022 train"][measure]
                    draws = boot["2023"][measure] / boot["2022 train"][measure]
                    row[f"{measure}_vs_2022_train"] = ratio
                    row[f"{measure}_vs_2022_train_lower_95"] = float(np.quantile(draws, 0.025))
                    row[f"{measure}_vs_2022_train_upper_95"] = float(np.quantile(draws, 0.975))
            rows.append(row)
    return pd.DataFrame(rows)


def ae_components(
    frozen: FrozenModel, oot: OutOfTime, train: Parts, later: Parts, n_boot: int = N_BOOT
) -> pd.DataFrame:
    """The 2023 A/E of both models, and the frequency, severity and large-claim ratios behind it.

    Both models are balanced on 2022 train, so their A/E on train is 1. The A/E of the technical
    model on 2023 is therefore the product of the three ratios of 2023 to train (frequency, severity
    beyond the price index and large claims), and the mix of people cancels. The tariff has an
    overall A/E only, because it is a single multiplicative model. Intervals resample households.
    """
    none = trend_options(frozen, oot, {"No trend": (1.0, "", "")}, n_boot).iloc[0]
    split = decomposition(train, later, n_boot).set_index("component")
    rows = [
        (
            "Technical model A/E",
            none["technical_a_e"],
            none["technical_lower_95"],
            none["technical_upper_95"],
        ),
        ("Tariff A/E", none["tariff_a_e"], none["tariff_lower_95"], none["tariff_upper_95"]),
    ]
    for name in (
        "Frequency (actual over expected claimants)",
        "Severity beyond the price index",
        "Large-claim contribution",
    ):
        line = split.loc[name]
        rows.append(
            (
                name,
                line["ratio"],
                1 + line["lower_95_percent"] / 100,
                1 + line["upper_95_percent"] / 100,
            )
        )
    return pd.DataFrame(rows, columns=["measure", "value", "lower_95", "upper_95"])
