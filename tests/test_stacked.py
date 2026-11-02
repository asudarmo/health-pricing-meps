"""Tests for the stacked candidate (issue #30)."""

import numpy as np
import pandas as pd
import pytest

from health_pricing.models import frame as mf
from health_pricing.models import glm, stacked

FACTORS = ["age", "benefit_type"]
TYPES = stacked.BENEFIT_TYPES


def stacked_frame(n=500, seed=11) -> pd.DataFrame:
    """Two rows per person: benefit type, an age band, exposure, capped cost and an event count."""
    rng = np.random.default_rng(seed)
    bands = ["30-34", "35-39", "40-44"]
    people = pd.DataFrame(
        {
            "DUPERSID": [f"p{i}" for i in range(n)],
            "age": rng.choice(bands, n),
            "exposure": rng.uniform(0.3, 1.0, n),
        }
    )
    rows = people.loc[people.index.repeat(2)].reset_index(drop=True)
    rows["benefit_type"] = TYPES * n
    inpatient = rows["benefit_type"] == "inpatient_daycase"
    rate = np.where(inpatient, 0.15, 0.5) * np.where(rows["age"] == "40-44", 1.6, 1.0)
    claimed = rng.random(len(rows)) < 1 - np.exp(-rate * rows["exposure"])
    rows["capped_cost"] = np.where(claimed, rng.gamma(2.0, np.where(inpatient, 9000, 700)), 0.0)
    rows["event_count"] = rng.integers(0, 20, len(rows))
    rows["age"] = pd.Categorical(rows["age"], categories=bands)
    rows["benefit_type"] = pd.Categorical(rows["benefit_type"], categories=TYPES)
    return rows


def fit(rows, parts=(), **kwargs):
    return glm.fit_two_part(
        rows,
        "cloglog",
        FACTORS,
        interaction=stacked.INTERACTION if parts else None,
        groups=rows["DUPERSID"].astype("category").cat.codes,
        interaction_parts=parts,
        **kwargs,
    )


def test_annual_cost_is_the_sum_over_benefit_types_for_a_hand_made_profile():
    rows = stacked_frame()
    model = fit(rows)
    person = pd.DataFrame(
        {
            "DUPERSID": ["new", "new"],
            "age": pd.Categorical(["40-44", "40-44"], categories=["30-34", "35-39", "40-44"]),
            "benefit_type": pd.Categorical(TYPES, categories=TYPES),
            "exposure": [0.5, 0.5],
        }
    )
    total = 0.0
    for benefit in TYPES:
        terms = ["const", "age=40-44"] + (
            ["benefit_type=inpatient_daycase"] if benefit != TYPES[0] else []
        )
        eta = sum(model.frequency.params[t] for t in terms) + np.log(0.5)
        severity = np.exp(sum(model.severity.params[t] for t in terms))
        total += (1 - np.exp(-np.exp(eta))) * severity * 1.065
    persons = pd.DataFrame({"DUPERSID": ["new"]})
    got = stacked.predict_person_year(model, person, persons)
    assert got.iloc[0] == pytest.approx(total)


def test_person_year_predictions_follow_the_order_of_the_person_frame():
    rows = stacked_frame(n=60)
    model = fit(rows)
    persons = pd.DataFrame({"DUPERSID": rows["DUPERSID"].drop_duplicates().to_numpy()[::-1]})
    got = stacked.predict_person_year(model, rows, persons)
    manual = pd.Series(model.predict(rows), index=rows["DUPERSID"]).groupby(level=0).sum()
    assert got.to_numpy() == pytest.approx(manual.loc[persons["DUPERSID"]].to_numpy())
    assert not got.isna().any()


def test_the_event_count_is_not_a_weight_or_a_predictor():
    rows = stacked_frame()
    base = fit(rows)
    shuffled = rows.assign(event_count=np.random.default_rng(2).permutation(rows["event_count"]))
    other = fit(shuffled)
    assert "event_count" not in glm.design_matrix(rows, FACTORS).columns
    for part in ("frequency", "severity"):
        assert np.allclose(getattr(base, part).params, getattr(other, part).params)
        assert getattr(base, part).model.freq_weights.max() == 1.0


def test_clustering_changes_the_standard_errors_and_not_the_coefficients():
    rows = stacked_frame()
    clustered = fit(rows)
    plain = glm.fit_two_part(rows, "cloglog", FACTORS)
    assert np.allclose(clustered.frequency.params, plain.frequency.params)
    assert not np.allclose(clustered.frequency.bse, plain.frequency.bse)
    assert clustered.frequency.cov_type == "cluster"


def test_the_interaction_can_sit_in_one_part_only():
    rows = stacked_frame()
    main = fit(rows)
    freq = fit(rows, ("frequency",))
    assert not any(":" in c for c in main.frequency_columns + main.severity_columns)
    assert any(":" in c for c in freq.frequency_columns)
    assert not any(":" in c for c in freq.severity_columns)
    assert freq.parameters > main.parameters
    # the prediction still works with the extra columns
    assert len(freq.predict(rows)) == len(rows)


def test_interaction_tests_report_both_parts_and_pick_the_significant_one():
    rows = stacked_frame(n=900)
    rows["DUPERSID"] = rows["DUPERSID"].astype(str)
    tests = stacked.interaction_tests(rows, FACTORS)
    assert list(tests["part"]) == ["frequency", "severity"]
    assert (tests["df"] == 2).all()  # (2 benefit types - 1) x (3 age bands - 1)
    assert stacked.significant_parts(
        pd.DataFrame({"part": ["a", "b"], "p_value": [0.01, 0.4]})
    ) == ("a",)


def _built() -> bool:
    import duckdb

    from health_pricing.data.load import DUCKDB_PATH

    if not DUCKDB_PATH.exists():
        return False
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'mart_person_year_benefit'"
        ).fetchone()
        return row[0] == 1
    finally:
        con.close()


@pytest.mark.skipif(not _built(), reason="run the load script and dbt build")
def test_real_benefit_frames_match_the_person_year_frames():
    raw = mf.load_frames()
    persons = glm.prepare_frames(raw)
    benefit = stacked.load_benefit_frames(raw)
    for name in ("train", "test"):
        rows, people = getattr(benefit, name), getattr(persons, name)
        assert len(rows) == 2 * len(people)
        assert rows["capped_cost"].sum() == pytest.approx(people["capped_cost"].sum())
        assert rows["cost"].sum() == pytest.approx(people["cost"].sum())
        assert list(rows["age"].cat.categories) == list(people["age"].cat.categories)
    model = stacked.fit_stacked(benefit.train)
    predicted = stacked.predict_person_year(model, benefit.test, persons.test)
    assert predicted.notna().all() and len(predicted) == len(persons.test)


def test_the_interaction_prediction_adds_the_cell_effect_for_one_benefit_type():
    rows = stacked_frame()
    model = fit(rows, ("frequency",))
    person = pd.DataFrame(
        {
            "age": pd.Categorical(["40-44"], categories=["30-34", "35-39", "40-44"]),
            "benefit_type": pd.Categorical(["inpatient_daycase"], categories=TYPES),
            "exposure": [1.0],
        }
    )
    terms = ["const", "age=40-44", "benefit_type=inpatient_daycase"]
    cell = "benefit_type=inpatient_daycase:age=40-44"
    eta = sum(model.frequency.params[t] for t in [*terms, cell])
    severity = np.exp(sum(model.severity.params[t] for t in terms))
    assert model.predict_capped(person)[0] == pytest.approx((1 - np.exp(-np.exp(eta))) * severity)


def test_no_count_column_is_a_rating_factor_or_a_design_column():
    assert not {"claim_count", "event_count"} & set(mf.FACTORS)
    assert not {"claim_count", "event_count"} & set(stacked.BENEFIT_FACTORS)
