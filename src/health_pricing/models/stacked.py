"""Candidate (c): the two-part GLM stacked by benefit type (issue #30).

The benefit-type table has one row per person-year per benefit type. `benefit_type` enters both
GLMs as a factor, and the capped person-year cost is shared between the types in proportion to
their uncapped cost. A person's rows are correlated, so standard errors are clustered by person.
The predicted annual cost of a person-year is the sum over its benefit types. The event count is
never used.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from health_pricing.data.load import DUCKDB_PATH
from health_pricing.models import glm, large_claims, levels
from health_pricing.models.frame import FACTORS, MODEL_YEAR, Frames

BENEFIT_TYPES = ["outpatient", "inpatient_daycase"]  # the first is the reference
BENEFIT_FACTORS = [*FACTORS, "benefit_type"]
INTERACTION = ("benefit_type", "age")


def load_benefit_frames(frames: Frames, con: duckdb.DuckDBPyConnection | None = None) -> Frames:
    """Benefit-type train and test frames with the approved grouping and cap.

    `frames` are the person-year frames before grouping, which fix the level grouping. The rows
    carry the person key for clustering and for adding the types back up. Do not display them.
    """
    own = con is None
    con = con or duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        columns = ", ".join(FACTORS)
        mart = con.execute(
            f"SELECT DUPERSID, year, split, benefit_type, {columns}, exposure, claimant, "
            f"cost_2023_prices AS cost FROM mart_person_year_benefit "
            f"WHERE year = {MODEL_YEAR} AND split IN ('train', 'test')"
        ).fetchdf()
    finally:
        if own:
            con.close()
    parts = {}
    for split in ("train", "test"):
        part = mart[mart["split"] == split].reset_index(drop=True)
        part["capped_cost"] = large_claims.capped_benefit_cost(part, cost="cost")
        parts[split] = part
    grouped = levels.apply_grouping(
        Frames(parts["train"], parts["test"], {}), levels.decided_grouping(frames)
    )
    for part in (grouped.train, grouped.test):
        part["benefit_type"] = pd.Categorical(part["benefit_type"], categories=BENEFIT_TYPES)
    return grouped


def fit_stacked(train: pd.DataFrame, interaction_parts: tuple[str, ...] = ()) -> glm.TwoPartModel:
    """Candidate (c): cloglog frequency and Gamma severity, with errors clustered by person.

    The `benefit_type` x age interaction is added to the parts named in `interaction_parts`.
    """
    return glm.fit_two_part(
        train,
        "cloglog",
        factors=BENEFIT_FACTORS,
        name="stacked",
        interaction=INTERACTION if interaction_parts else None,
        groups=train["DUPERSID"].astype("category").cat.codes,
        interaction_parts=interaction_parts,
    )


def predict_person_year(
    model: glm.TwoPartModel, benefit: pd.DataFrame, persons: pd.DataFrame
) -> pd.Series:
    """Annual cost of each person-year: the sum over benefit types, in the order of `persons`."""
    predicted = pd.Series(model.predict(benefit), index=benefit["DUPERSID"].to_numpy())
    total = predicted.groupby(level=0).sum()
    return total.reindex(persons["DUPERSID"].to_numpy()).set_axis(persons.index)


def interaction_tests(train: pd.DataFrame, factors: list[str] = BENEFIT_FACTORS) -> pd.DataFrame:
    """Likelihood-ratio tests of the `benefit_type` x age interaction, for each part.

    Both models are fitted without clustering, because the test needs the model likelihood. The
    clustered standard errors of the final model are in the coefficient table.
    """
    plain = glm.fit_two_part(train, "cloglog", factors, "plain")
    crossed = glm.fit_two_part(train, "cloglog", factors, "crossed", INTERACTION)
    return pd.DataFrame(
        [
            glm.deviance_test(plain, crossed, "frequency"),
            glm.deviance_test(plain, crossed, "severity"),
        ]
    )


def significant_parts(tests: pd.DataFrame, alpha: float = 0.05) -> tuple[str, ...]:
    """The parts whose interaction test has a p-value below `alpha`."""
    return tuple(tests.loc[tests["p_value"] < alpha, "part"])
