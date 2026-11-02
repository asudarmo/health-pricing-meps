"""Population stability index (PSI) of the mix and predicted cost, 2022 train and 2023 (M5, #46).

PSI measures how far the share of exposure across levels or bins moved between two periods, as the
sum over levels of `(share 2023 - share 2022) * ln(share 2023 / share 2022)`. The reading bands
below 0.1, 0.1 to 0.25 and above 0.25 are conventions of credit scoring and not tests. Because a PSI
is never negative, sampling noise alone gives it a positive value, so each PSI is shown with a
household-resampled interval and with the value that noise alone would give. Tables hold aggregates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from health_pricing.models import factors, large_claims, trend
from health_pricing.models.outofsample import TARIFF, TECHNICAL, FrozenModel, OutOfTime

SEED = trend.SEED
N_BOOT = trend.N_BOOT
FLOOR = 1e-4  # a share below this is raised to it, so an empty level does not give an infinite PSI
BAND_LOW, BAND_HIGH = 0.1, 0.25
N_BINS = 10


def psi(earlier: np.ndarray, later: np.ndarray) -> np.ndarray:
    """PSI from two arrays of exposure by level. The last axis is the level."""
    p = np.maximum(earlier / earlier.sum(axis=-1, keepdims=True), FLOOR)
    q = np.maximum(later / later.sum(axis=-1, keepdims=True), FLOOR)
    return np.sum((q - p) * np.log(q / p), axis=-1)


def reading(value: float) -> str:
    """The conventional reading band of a PSI."""
    if value < BAND_LOW:
        return "below 0.1"
    return "0.1 to 0.25" if value <= BAND_HIGH else "above 0.25"


def _household_matrix(
    households: np.ndarray, codes: np.ndarray, n_levels: int, weight
) -> np.ndarray:
    """Household by level sums of `weight`, the input of the bootstrap."""
    count = households.max() + 1
    out = np.zeros((count, n_levels))
    np.add.at(out, (households, codes), weight)
    return out


def _interval(
    first: np.ndarray, second: np.ndarray, n_boot: int, seed: int
) -> tuple[float, float, float]:
    """The PSI, and the 2.5 and 97.5 percentiles of its household resamples.

    Resampling adds sampling noise to both periods, and a PSI cannot be negative, so the interval
    sits above the PSI of the data when the true PSI is near zero.
    """
    sums = trend.resampled_sums(first, n_boot, seed), trend.resampled_sums(second, n_boot, seed + 1)
    values = psi(sums[0], sums[1])
    low, high = np.quantile(values, [0.025, 0.975])
    return float(psi(first.sum(axis=0), second.sum(axis=0))), float(low), float(high)


def _noise_floor(n_levels: int, rows_first: int, rows_second: int) -> float:
    """The PSI that sampling noise alone gives, to a first approximation.

    For two independent samples from the same distribution, the expected PSI is close to
    `(levels - 1) * (1 / n1 + 1 / n2)`, with `n` the number of person-years in each period.
    """
    return (n_levels - 1) * (1 / rows_first + 1 / rows_second)


def _row(
    name: str,
    kind: str,
    codes_first: np.ndarray,
    codes_second: np.ndarray,
    first: trend.Parts,
    second: trend.Parts,
    n_levels: int,
    n_boot: int,
    seed: int,
) -> dict:
    matrix_first = _household_matrix(first.households, codes_first, n_levels, first.t)
    matrix_second = _household_matrix(second.households, codes_second, n_levels, second.t)
    value, low, high = _interval(matrix_first, matrix_second, n_boot, seed)
    return {
        "measure": name,
        "kind": kind,
        "levels": n_levels,
        "psi": value,
        "lower_95": low,
        "upper_95": high,
        "noise_only_psi": _noise_floor(n_levels, len(codes_first), len(codes_second)),
        "reading": reading(value),
    }


def _codes(series: pd.Series, categories: list) -> np.ndarray:
    return pd.Categorical(series, categories=categories).codes.astype(int)


def factor_psi(
    frozen: FrozenModel,
    oot: OutOfTime,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> pd.DataFrame:
    """PSI of each rating factor and analysis-only factor, with its level table of shares.

    Age is in its five-year bands and the levels are those of the M3 grouping.
    """
    first = trend.train_parts(frozen)
    second = trend.out_of_time_parts(frozen, oot)
    rating = factors.FINAL_RATING
    controls = frozen.controls
    rows = []
    for position, name in enumerate([*rating, *controls]):
        categories = list(first.frame[name].cat.categories)
        rows.append(
            _row(
                name,
                "rating" if name in rating else "analysis_only",
                _codes(first.frame[name], categories),
                _codes(second.frame[name], categories),
                first,
                second,
                len(categories),
                n_boot,
                seed + 2 * position,
            )
        )
    return pd.DataFrame(rows)


def level_shares(frozen: FrozenModel, oot: OutOfTime, names: list[str]) -> pd.DataFrame:
    """Exposure share of each level in each period, and the part of the PSI each level carries."""
    first = trend.train_parts(frozen)
    second = trend.out_of_time_parts(frozen, oot)
    rows = []
    for name in names:
        categories = list(first.frame[name].cat.categories)
        shares = []
        for pieces in (first, second):
            codes = _codes(pieces.frame[name], categories)
            exposure = np.bincount(codes, weights=pieces.t, minlength=len(categories))
            shares.append(np.maximum(exposure / exposure.sum(), FLOOR))
        p, q = shares
        for level, a, b in zip(categories, p, q, strict=True):
            rows.append(
                {
                    "factor": name,
                    "level": level,
                    "share_2022": a,
                    "share_2023": b,
                    "psi_part": (b - a) * np.log(b / a),
                }
            )
    return pd.DataFrame(rows)


def most_moved(shares: pd.DataFrame, top: int = 3) -> pd.DataFrame:
    """The levels that carry most of the PSI of each factor, largest first."""
    out = shares.sort_values(["factor", "psi_part"], ascending=[True, False])
    return out.groupby("factor").head(top).reset_index(drop=True)


def _unit(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(exposure=1.0)


def cost_per_exposure_year(frozen: FrozenModel, oot: OutOfTime) -> dict[str, dict[str, np.ndarray]]:
    """Predicted annual cost for a full year, per model and period, with no trend applied.

    The technical model has the large-claim load and the rebalancing, and the tariff is its
    surrogate. A trend is a level factor, so it would move every row into higher bins together and
    would not measure a change of mix.
    """
    out: dict[str, dict[str, np.ndarray]] = {TECHNICAL: {}, TARIFF: {}}
    load = 1 + large_claims.PROVISIONAL_LOAD
    for period, frame in (
        ("2022", frozen.final_tariff.frames["spline"].train),
        ("2023", oot.spline_frame),
    ):
        pieces = trend.parts(frozen, _unit(frame))
        out[TECHNICAL][period] = frozen.balance * load * pieces.p * pieces.mu
        out[TARIFF][period] = frozen.tariff(_unit(frame))
    return out


def weighted_edges(values: np.ndarray, weights: np.ndarray, n_bins: int = N_BINS) -> np.ndarray:
    """Interior bin edges at the exposure-weighted quantiles of `values`."""
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order]) / weights.sum()
    targets = np.arange(1, n_bins) / n_bins
    return np.unique(values[order][np.searchsorted(cumulative, targets)])


def predicted_cost_psi(
    frozen: FrozenModel,
    oot: OutOfTime,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """PSI of predicted cost per exposure year in ten bins set on 2022 train, for both models.

    Returns the PSI rows and the share of exposure in each bin for each period.
    """
    first = trend.train_parts(frozen)
    second = trend.out_of_time_parts(frozen, oot)
    predicted = cost_per_exposure_year(frozen, oot)
    rows, shares = [], []
    for position, (model, values) in enumerate(predicted.items()):
        edges = weighted_edges(values["2022"], first.t)
        n_bins = len(edges) + 1
        codes = {
            period: np.searchsorted(edges, values[period], side="left")
            for period in ("2022", "2023")
        }
        rows.append(
            _row(
                f"Predicted cost, {model}",
                "predicted_cost",
                codes["2022"],
                codes["2023"],
                first,
                second,
                n_bins,
                n_boot,
                seed + 100 + 2 * position,
            )
        )
        for period, pieces in (("2022", first), ("2023", second)):
            exposure = np.bincount(codes[period], weights=pieces.t, minlength=n_bins)
            for bin_number, share in enumerate(exposure / exposure.sum(), start=1):
                shares.append(
                    {"model": model, "period": period, "bin": bin_number, "share": float(share)}
                )
    return pd.DataFrame(rows), pd.DataFrame(shares)
