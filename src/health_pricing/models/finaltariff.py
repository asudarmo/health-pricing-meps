"""The v1-lite final tariff (M6, issue #37).

The final tariff is the M3 multiplicative tariff (a surrogate of the technical model, with
five-year age bands) after the monotone adult age rule of `agemonotone` and a rebalancing of the
base rate. It is fitted on 2022 train. The rating-period level is the forecast trend and the
decided credibility-weighted rebase applied to the base rate. The pooled refit with a year term
is v2 work. This module reports how well the tariff approximates the technical model by segment
and builds the relativities table of the published contract (`_docs/plan.md` section 6).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from health_pricing.models import agemonotone, outofsample, relativities
from health_pricing.models.outofsample import FrozenModel

FORECAST_TREND = 1.019  # the central external trend of gate 4, applied to 2022 cost
DECIDED_REBASE = 1.06  # the user's credibility-weighted rebase on the forecast cost
RATING_LEVEL = FORECAST_TREND * DECIDED_REBASE
CONDITIONS = ["HIBPDX", "CHDDX", "CANCERDX", "ARTHDX", "ASTHDX", "CHOLDX", "OHRTDX"]
OUTPUT_DIR = agemonotone.OUTPUT_DIR


def _segments(frame: pd.DataFrame, technical: np.ndarray) -> pd.DataFrame:
    """One row per person-year and segment, with the segment type and label."""
    conditions = sum((frame[c].astype(str) == "1").astype(int) for c in CONDITIONS)
    rank = pd.Series(technical, index=frame.index).rank(method="first")
    decile = pd.qcut(rank, 10, labels=False) + 1
    labels = {
        "age band": frame["age"].astype(str),
        "predicted cost decile": decile.astype(str).str.zfill(2),
        "number of conditions": conditions.clip(upper=3).map(
            {0: "0", 1: "1", 2: "2", 3: "3 or more"}
        ),
    }
    for factor in ["region", *CONDITIONS]:
        labels[f"factor level|{factor}"] = factor + "=" + frame[factor].astype(str)
    parts = []
    for kind, label in labels.items():
        kind = kind.split("|")[0]
        parts.append(
            pd.DataFrame(
                {"segment_type": kind, "segment": label.to_numpy(), "_row": np.arange(len(frame))}
            )
        )
    return pd.concat(parts, ignore_index=True)


def approximation_error(
    frozen: FrozenModel, adjusted: agemonotone.AdjustedTariff, split: str
) -> pd.DataFrame:
    """Tariff over technical model by segment, before and after the age rule.

    The ratio of a segment is its total tariff cost over its total technical-model cost.
    """
    frame = getattr(frozen.final_tariff.frames["spline"], split)
    technical = frozen.technical(frame)
    long = _segments(frame, technical)
    row = long["_row"].to_numpy()
    long["exposure"] = frame["exposure"].to_numpy()[row]
    long["technical"] = technical[row]
    long["tariff_before_rule"] = frozen.tariff(frame)[row]
    long["tariff_final"] = adjusted.predict(frame)[row]
    table = long.drop(columns="_row").groupby(["segment_type", "segment"]).sum().reset_index()
    table["ratio_before_rule"] = table["tariff_before_rule"] / table["technical"]
    table["ratio_final"] = table["tariff_final"] / table["technical"]
    table.insert(0, "split", split)
    return table


def error_summary(errors: pd.DataFrame) -> pd.DataFrame:
    """Median and maximum absolute departure of the ratio from 1, by split and segment type."""
    rows = []
    for (split, kind), part in errors.groupby(["split", "segment_type"]):
        row = {"split": split, "segment_type": kind, "segments": len(part)}
        for column in ("before_rule", "final"):
            departure = (part[f"ratio_{column}"] - 1).abs()
            row[f"median_abs_departure_{column}"] = float(departure.median())
            row[f"max_abs_departure_{column}"] = float(departure.max())
            row[f"worst_segment_{column}"] = part.loc[departure.idxmax(), "segment"]
        rows.append(row)
    return pd.DataFrame(rows)


def relativity_table(frozen: FrozenModel, adjusted: agemonotone.AdjustedTariff) -> pd.DataFrame:
    """The final tariff's relativities in the section 6 columns.

    Age is shown against the adult band with the most exposure, as in presentation elsewhere, so
    the base rate carries that band's relativity. Bounds keep the width of the technical model's
    combined bounds (frequency and severity treated as independent) and are centred on the tariff
    relativity. They show model uncertainty and are not a fit of the tariff. The adult band that
    age is shown against has no bounds, because the model measures age against it.
    """
    train = frozen.prepared.train
    params = adjusted.coefficients
    original = frozen.final_tariff.tariff.result.params
    reference = relativities.age_reference_for_presentation(frozen.raw)
    model = pd.read_csv(relativities.OUTPUT_DIR / "relativities_combined_pure_premium.csv")
    model = model.set_index(["factor", "level"])
    model.index = model.index.set_levels(model.index.levels[1].astype(str), level=1)
    divisor = float(np.exp(original[f"age={reference}"]))
    rows = []
    for factor in frozen.final_tariff.tariff.factors:
        prefix = "presentation_" if factor == "age" else ""
        for position, level in enumerate(train[factor].cat.categories):
            term = f"{factor}={level}"
            if position > 0 and term not in params.index:
                continue
            value = 1.0 if position == 0 else float(np.exp(params[term]))
            value /= divisor if factor == "age" else 1.0
            exposure = train.loc[train[factor] == level, "exposure"].sum()
            if exposure <= 0:
                continue
            low = high = np.nan
            if (factor, str(level)) in model.index:
                shape = model.loc[(factor, str(level))]
                scale = value / shape[f"{prefix}relativity"]
                low, high = scale * shape[f"{prefix}lower_95"], scale * shape[f"{prefix}upper_95"]
                if position > 0 and np.isclose(low, high):
                    low = high = np.nan  # the model measures age against this band, so no bounds
            rows.append(
                {
                    "factor": factor,
                    "level": str(level),
                    "relativity": value,
                    "exposure": float(exposure),
                    "lower_95": low,
                    "upper_95": high,
                    "is_reference": position == 0,
                    "age_rule_applied": bool(
                        term in params.index and abs(params[term] - original.get(term, 0.0)) > 1e-9
                    ),
                }
            )
    return pd.DataFrame(rows)


def base_rate_table(frozen: FrozenModel, adjusted: agemonotone.AdjustedTariff) -> pd.DataFrame:
    """The base rate at 2022 level and at the rating-period level, for the reference profile."""
    reference = relativities.age_reference_for_presentation(frozen.raw)
    original = frozen.final_tariff.tariff.result.params
    base = adjusted.balance * float(np.exp(original["const"] + original[f"age={reference}"]))
    return pd.DataFrame(
        {
            "component": ["base rate at 2022 level", "forecast trend", "rebase", "base rate"],
            "value": [base, FORECAST_TREND, DECIDED_REBASE, base * RATING_LEVEL],
        }
    )


def save_all(frozen: FrozenModel | None = None) -> dict[str, pd.DataFrame]:
    """Build the final tariff tables and save them under `outputs/m6_draft/`."""
    frozen = frozen or outofsample.freeze()
    adjusted = agemonotone.adjust(frozen)
    errors = pd.concat(
        [approximation_error(frozen, adjusted, s) for s in ("train", "test")], ignore_index=True
    )
    tables = {
        "final_tariff_relativities.csv": relativity_table(frozen, adjusted),
        "final_tariff_base_rate.csv": base_rate_table(frozen, adjusted),
        "final_tariff_approximation_error.csv": errors,
        "final_tariff_approximation_summary.csv": error_summary(errors),
    }
    for name, table in tables.items():
        outofsample.save_table(table, name, OUTPUT_DIR)
    return tables


if __name__ == "__main__":
    save_all()
