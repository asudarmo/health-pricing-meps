"""Evidence for the large-claim cap (issue #27, decision gate 5).

The cap applies to annual cost per person-year, so `mart_person_year` does not change. Cost is the
PMI-scope cost at 2023 prices. Every table is an aggregate over claimants (person-years with at
least one claim) and is built from the 2022 train split, with the test split used only to check
that a cap set on train behaves the same on rows it has not seen. The user approved the cap and the
provisional load at decision gate 5 on 2026-11-02, and the functions at the end apply them.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models.frame import MODEL_YEAR, Frames

# Approved at gate 5. The cap is on annual PMI-scope cost per person-year at 2023 prices. The load
# is the train excess over capped cost (6.47%, rounded to 6.5%). It is provisional, used to compare
# the candidate structures only, and is not set from the test split or from 2023.
LARGE_CLAIM_CAP = 100_000.0
PROVISIONAL_LOAD = 0.065

PERCENTILES = (50, 60, 70, 75, 80, 90, 95, 97.5, 99, 99.5, 99.9)
# Candidate caps. A percentile cap is that percentile of train cost per claimant, a fixed cap is a
# dollar amount at 2023 prices.
PERCENTILE_CAPS = (99.0, 99.5, 99.9)
FIXED_CAPS = (50_000.0, 100_000.0, 250_000.0)
AGE_GROUPS = ((0, 17, "0-17"), (18, 39, "18-39"), (40, 64, "40-64"), (65, 200, "65+"))


def percentile_label(percentile: float) -> str:
    return f"P{percentile:g}"


def fixed_label(amount: float) -> str:
    return f"${amount:,.0f}"


def percentile_table(cost: pd.Series, percentiles=PERCENTILES) -> pd.DataFrame:
    """Percentiles of annual cost per claimant, then the maximum."""
    rows = [
        {"percentile": percentile_label(p), "cost_per_claimant": cost.quantile(p / 100)}
        for p in percentiles
    ]
    rows.append({"percentile": "Max", "cost_per_claimant": cost.max()})
    return pd.DataFrame(rows)


def resolve_caps(train_cost: pd.Series) -> dict[str, float]:
    """Dollar amount of every candidate cap, with percentile caps set on train claimants."""
    caps = {percentile_label(p): float(train_cost.quantile(p / 100)) for p in PERCENTILE_CAPS}
    caps.update({fixed_label(a): a for a in FIXED_CAPS})
    return dict(sorted(caps.items(), key=lambda item: item[1]))


def cap_comparison(cost: pd.Series, caps: dict[str, float]) -> pd.DataFrame:
    """For each cap, the claimants and cost above it and the effect on mean severity.

    `cost` is annual cost per claimant. Mean severity is total cost over claimants. The excess is
    the part of each claimant's cost above the cap.
    """
    total = cost.sum()
    rows = []
    for label, cap in caps.items():
        above = cost > cap
        excess = (cost - cap).clip(lower=0).sum()
        capped_mean = (total - excess) / len(cost)
        rows.append(
            {
                "cap": label,
                "cap_amount": cap,
                "claimants_above": int(above.sum()),
                "share_of_claimants_above": above.mean(),
                "share_of_cost_above_cap": excess / total,
                "mean_severity": cost.mean(),
                "mean_severity_capped": capped_mean,
                "change_in_mean_severity": capped_mean / cost.mean() - 1,
            }
        )
    return pd.DataFrame(rows)


def stability_table(train_cost: pd.Series, test_cost: pd.Series, caps: dict[str, float]):
    """Train caps applied to train and test claimants, to see if the tail behaves the same."""
    rows = []
    for label, cap in caps.items():
        row = {"cap": label, "cap_amount": cap}
        for name, cost in (("train", train_cost), ("test", test_cost)):
            row[f"{name}_claimants_above"] = int((cost > cap).sum())
            row[f"{name}_share_of_cost_above_cap"] = (cost - cap).clip(lower=0).sum() / cost.sum()
        rows.append(row)
    return pd.DataFrame(rows)


def age_group(age: pd.Series) -> pd.Series:
    ages = age.astype(int)
    out = pd.Series(index=age.index, dtype="object")
    for low, high, label in AGE_GROUPS:
        out[(ages >= low) & (ages <= high)] = label
    return out


def excess_load_table(frame: pd.DataFrame, cap: float, by: str | None = None) -> pd.DataFrame:
    """The excess above a cap as a percentage of capped cost, overall or by segment.

    `frame` holds claimants only, with `cost`. The load is the excess cost over the capped cost, so
    it is the factor to add to capped cost to recover the uncapped total. `by` names a column.
    """
    work = frame.assign(
        capped=frame["cost"].clip(upper=cap), excess=(frame["cost"] - cap).clip(lower=0)
    )
    work["above"] = work["excess"] > 0
    if by is None:
        work = work.assign(segment="All claimants")
        by = "segment"
    table = work.groupby(by).agg(
        claimants=("cost", "size"),
        claimants_above=("above", "sum"),
        capped_cost=("capped", "sum"),
        excess_cost=("excess", "sum"),
    )
    table["excess_load"] = table["excess_cost"] / table["capped_cost"]
    return table.reset_index(names="segment")


def load_benefit_claimants(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Claimants by benefit type for the 2022 train and test splits, with age and cost.

    The rows carry the person key so costs can be capped per person-year. Do not display them.
    """
    own = con is None
    con = con or duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        return con.execute(
            "SELECT DUPERSID, year, split, benefit_type, age, cost_2023_prices AS cost "
            "FROM mart_person_year_benefit "
            f"WHERE year = {MODEL_YEAR} AND split IN ('train', 'test') AND claimant = 1"
        ).fetchdf()
    finally:
        if own:
            con.close()


def benefit_cap_comparison(claimants: pd.DataFrame) -> pd.DataFrame:
    """The cap comparison for each benefit type, with percentile caps set within the type."""
    train = claimants[claimants["split"] == "train"]
    rows = []
    for benefit, rows_in_type in train.groupby("benefit_type"):
        cost = rows_in_type["cost"]
        table = cap_comparison(cost, resolve_caps(cost))
        table.insert(0, "benefit_type", benefit)
        table.insert(1, "claimants", len(cost))
        rows.append(table)
    return pd.concat(rows, ignore_index=True)


def capped_cost(cost, cap: float = LARGE_CLAIM_CAP):
    """Annual cost per person-year limited to the cap. The excess is `cost - capped_cost(cost)`."""
    return cost.clip(upper=cap) if hasattr(cost, "clip") else min(cost, cap)


def cap_frames(frames: Frames, cap: float = LARGE_CLAIM_CAP) -> Frames:
    """The train and test frames with a `capped_cost` column. The `cost` column is unchanged."""
    return Frames(
        frames.train.assign(capped_cost=capped_cost(frames.train["cost"], cap)),
        frames.test.assign(capped_cost=capped_cost(frames.test["cost"], cap)),
        frames.reference_levels,
    )


def capped_benefit_cost(
    benefit: pd.DataFrame,
    cap: float = LARGE_CLAIM_CAP,
    cost: str = "cost_2023_prices",
    keys: tuple[str, ...] = ("DUPERSID", "year"),
) -> pd.Series:
    """Benefit-type cost after capping the person-year total, shared by uncapped cost.

    Each person-year's total over its benefit-type rows is capped, and every row keeps its share of
    that total. A person-year under the cap is unchanged and one with no cost stays at zero. The
    capped rows add up to the capped person-year cost.
    """
    total = benefit.groupby(list(keys))[cost].transform("sum")
    scale = (cap / total).where(total > cap, 1.0)
    return benefit[cost] * scale


def with_load(prediction, load: float = PROVISIONAL_LOAD):
    """A capped prediction plus the large-claim load, which is a percentage of capped cost."""
    return prediction * (1 + load)


def capped_summary(frames: Frames) -> pd.DataFrame:
    """Cost, capped cost and the excess for each split, from frames made by `cap_frames`.

    The test row is a check only. The provisional load is set from train and not from test.
    """
    rows = []
    for name, frame in (("train", frames.train), ("test", frames.test)):
        cost, capped = frame["cost"].sum(), frame["capped_cost"].sum()
        rows.append(
            {
                "split": name,
                "person_years": len(frame),
                "claimants_above_cap": int((frame["cost"] > LARGE_CLAIM_CAP).sum()),
                "cost": cost,
                "capped_cost": capped,
                "excess": cost - capped,
                "excess_load": (cost - capped) / capped,
            }
        )
    return pd.DataFrame(rows)
