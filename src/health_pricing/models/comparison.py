"""Compares the candidate model structures on one yardstick (issue #32, decision gate 7).

Every candidate is fitted on the 2022 train split and scored on the 2022 test split with the same
metrics code. Predictions are expected annual cost per person-year at 2023 prices, with the
provisional large-claim load, and actual cost is the uncapped annual cost. All tables are
aggregates. The comparison informs the choice of structure and does not make it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from health_pricing.models import glm, large_claims, metrics, stacked
from health_pricing.models.frame import FACTORS, Frames

COMPARISON_PATH = glm.SCORES_DIR / "model_comparison.csv"
AE_LOW, AE_HIGH = 0.85, 1.15
MIN_CLAIMANTS = 30
# Names used in every table, chart and saved file. The letter is the candidate of the plan.
NAME_A = "(a) Binomial-cloglog × Gamma"
NAME_B = "(b) Poisson × Gamma"
NAME_C = "(c) Stacked by benefit type"
NAME_C_AGE = "(c) Stacked with age × benefit interaction"
NAME_A_SURROGATE = "(a) Surrogate model (tariff)"
NAME_D = "(d) Event-based"
BASELINE = "Baseline (overall mean)"
NOT_FITTED = {NAME_D: "Optional event-based candidate, not fitted in this round."}


@dataclass
class Candidate:
    """A fitted candidate with its predictions on both splits."""

    name: str
    parameters: int
    train: np.ndarray
    test: np.ndarray
    train_unit: np.ndarray  # predicted cost of each train row if it had a full year of exposure
    test_unit: np.ndarray

    def prediction(self, split: str) -> np.ndarray:
        return getattr(self, split)

    def unit_prediction(self, split: str) -> np.ndarray:
        return getattr(self, f"{split}_unit")


def _person_year(model, rows: pd.DataFrame, persons: pd.DataFrame) -> np.ndarray:
    return stacked.predict_person_year(model, rows, persons).to_numpy()


def fit_candidates(raw: Frames) -> tuple[Frames, dict[str, Candidate]]:
    """Fit candidates a, b, c and c with the age interaction on the train split.

    `raw` are the frames from `frame.load_frames`. Returns the prepared (grouped and capped)
    frames and the candidates by name.
    """
    prepared = glm.prepare_frames(raw)
    benefit = stacked.load_benefit_frames(raw)
    train, test = prepared.train, prepared.test
    unit = {"train": train.assign(exposure=1.0), "test": test.assign(exposure=1.0)}
    benefit_unit = {s: getattr(benefit, s).assign(exposure=1.0) for s in ("train", "test")}
    tests = stacked.interaction_tests(benefit.train)
    candidates = {}
    for name, link in ((NAME_A, "cloglog"), (NAME_B, "poisson")):
        model = glm.fit_two_part(train, link, name=name)
        candidates[name] = Candidate(
            name,
            model.parameters,
            model.predict(train),
            model.predict(test),
            model.predict(unit["train"]),
            model.predict(unit["test"]),
        )
    for name, parts in ((NAME_C, ()), (NAME_C_AGE, stacked.significant_parts(tests))):
        model = stacked.fit_stacked(benefit.train, parts)

        candidates[name] = Candidate(
            name,
            model.parameters,
            _person_year(model, benefit.train, train),
            _person_year(model, benefit.test, test),
            _person_year(model, benefit_unit["train"], unit["train"]),
            _person_year(model, benefit_unit["test"], unit["test"]),
        )
    return prepared, candidates


def multiplicative_departure(unit_prediction: np.ndarray, matrix: pd.DataFrame) -> dict[str, float]:
    """How far predicted cost is from a base rate times a product of factor relativities.

    The prediction of a full year of exposure is regressed on the factor levels on the log scale.
    The fitted values are the closest multiplicative form. The departure of a row is its
    prediction over the fitted value, minus 1. A prediction that is exactly multiplicative has a
    departure of zero for every row. This is information only and is not used to choose a model.
    """
    log_prediction = np.log(np.asarray(unit_prediction, dtype=float))
    design = matrix.to_numpy()
    coefficients, *_ = np.linalg.lstsq(design, log_prediction, rcond=None)
    residual = log_prediction - design @ coefficients
    departure = np.abs(np.expm1(residual))
    return {
        "max_multiplicative_departure": float(departure.max()),
        "p99_multiplicative_departure": float(np.quantile(departure, 0.99)),
        "rms_log_departure": float(np.sqrt(np.mean(residual**2))),
    }


def comparison_table(prepared: Frames, candidates: dict[str, Candidate]) -> pd.DataFrame:
    """Scores of every candidate and the baseline on both splits, for the comparison csv."""
    frames = {"train": prepared.train, "test": prepared.test}
    rows = []
    baseline = metrics.baseline_scores(prepared.train, prepared.test).set_index("split")
    for split, frame in frames.items():
        scores = baseline.loc[split]
        by_power = metrics.deviance_by_power(
            frame["cost"], metrics.baseline_predictions(prepared.train, frame)
        )
        rows.append(
            {
                "candidate": BASELINE,
                "split": split,
                "tweedie_deviance": scores["tweedie_deviance"],
                "mean_tweedie_deviance": scores["mean_tweedie_deviance"],
                "tweedie_deviance_p1_3": by_power[1.3],
                "tweedie_deviance_p1_7": by_power[1.7],
                "gini": scores["gini"],
                "a_e": scores["a_e"],
                "parameters": 1,
                "max_multiplicative_departure": 0.0,
                "dropped_reason": "",
            }
        )
    for candidate in candidates.values():
        for split, frame in frames.items():
            row = glm.candidate_scores(
                candidate.name,
                candidate.parameters,
                {split: (frame, candidate.prediction(split))},
            ).iloc[0]
            matrix = glm.design_matrix(frame, FACTORS, rating=True)
            departure = multiplicative_departure(candidate.unit_prediction(split), matrix)
            rows.append(
                {**row, "max_multiplicative_departure": departure["max_multiplicative_departure"]}
            )
    for name, reason in NOT_FITTED.items():
        for split in frames:
            rows.append({"candidate": name, "split": split, "dropped_reason": reason})
    table = pd.DataFrame(rows)
    columns = [c for c in glm.SCORE_COLUMNS if c != "dropped_reason"]
    table = table[[*columns, "max_multiplicative_departure", "dropped_reason"]]
    reference = table[table["candidate"] == BASELINE][["split", "tweedie_deviance"]]
    table = metrics.add_deviance_reduction(table, reference)
    order = [*columns[:3], "deviance_reduction_pct", *columns[3:]]
    return table[[*order, "max_multiplicative_departure", "dropped_reason"]]


def save_comparison(table: pd.DataFrame, path: Path = COMPARISON_PATH) -> Path:
    """Save the comparison table. It holds aggregates only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)
    return path


def ranking_table(table: pd.DataFrame, split: str = "test") -> pd.DataFrame:
    """Candidates ranked by Tweedie deviance at p = 1.3, 1.5 and 1.7 (1 is the lowest deviance)."""
    scored = table[(table["split"] == split) & table["tweedie_deviance"].notna()]
    columns = ["tweedie_deviance_p1_3", "tweedie_deviance", "tweedie_deviance_p1_7"]
    ranks = scored.set_index("candidate")[columns].rank(method="min").astype(int)
    ranks.columns = ["rank_p1_3", "rank_p1_5", "rank_p1_7"]
    return ranks.reset_index()


def lift_comparison(
    frame: pd.DataFrame, candidates: dict[str, Candidate], split: str, n: int = 10
) -> pd.DataFrame:
    """A/E by decile of predicted cost for every candidate, side by side."""
    tables = {
        name: metrics.lift_table(
            frame["cost"], c.prediction(split), frame["exposure"], n
        ).set_index("group")["a_e"]
        for name, c in candidates.items()
    }
    return pd.DataFrame(tables).rename_axis("decile").reset_index()


def ae_flags(
    frame: pd.DataFrame, predicted, factors: list[str] = FACTORS, name: str = ""
) -> pd.DataFrame:
    """Factor levels with enough claimants whose A/E falls outside the 0.85 to 1.15 band."""
    table = metrics.ae_by_factor(frame, predicted, factors)
    big = table[table["claimants"] >= MIN_CLAIMANTS]
    flagged = big[(big["a_e"] < AE_LOW) | (big["a_e"] > AE_HIGH)].copy()
    flagged.insert(0, "candidate", name)
    return flagged.reset_index(drop=True)


def ae_flag_counts(
    frame: pd.DataFrame, candidates: dict[str, Candidate], split: str, capped: bool = False
) -> pd.DataFrame:
    """For each candidate, the factor levels checked and the number outside the A/E band.

    With `capped` set, actual cost is the capped cost and the prediction has no large-claim load,
    which removes the noise from a few very large claims.
    """
    rows = []
    for name, candidate in candidates.items():
        actual_frame, predicted = frame, candidate.prediction(split)
        if capped:
            actual_frame = frame.assign(cost=frame["capped_cost"])
            predicted = predicted / (1 + large_claims.PROVISIONAL_LOAD)
        table = metrics.ae_by_factor(actual_frame, predicted, FACTORS)
        big = table[table["claimants"] >= MIN_CLAIMANTS]
        outside = (big["a_e"] < AE_LOW) | (big["a_e"] > AE_HIGH)
        rows.append(
            {
                "candidate": name,
                "levels_checked": len(big),
                "levels_outside_band": int(outside.sum()),
                "worst_a_e": float(big.loc[(big["a_e"] - 1).abs().idxmax(), "a_e"]),
            }
        )
    return pd.DataFrame(rows)


def deviance_difference_interval(
    frame: pd.DataFrame,
    candidates: dict[str, Candidate],
    split: str = "test",
    reference: str = NAME_A,
    n_boot: int = 2000,
    seed: int = 20221102,
) -> pd.DataFrame:
    """How much of each candidate's deviance gap to a reference is sampling noise.

    Households are resampled with replacement, because members of a household are not
    independent. The table gives, for each candidate, the Tweedie deviance (p = 1.5) minus the
    reference's, with a 95 percent interval, and the share of resamples in which the candidate
    has the lower deviance. Positive means the candidate is worse than the reference.
    """
    rng = np.random.default_rng(seed)
    households = pd.factorize(frame["DUID"])[0]
    count = households.max() + 1
    draws = rng.integers(0, count, size=(n_boot, count))
    reference_unit = metrics.tweedie_unit_deviance(
        frame["cost"], candidates[reference].prediction(split)
    )
    rows = []
    for name, candidate in candidates.items():
        if name == reference:
            continue
        unit = metrics.tweedie_unit_deviance(frame["cost"], candidate.prediction(split))
        by_household = np.bincount(households, weights=unit - reference_unit, minlength=count)
        resampled = by_household[draws].sum(axis=1)
        rows.append(
            {
                "candidate": name,
                "versus": reference,
                "deviance_difference": float(by_household.sum()),
                "lower_95": float(np.quantile(resampled, 0.025)),
                "upper_95": float(np.quantile(resampled, 0.975)),
                "share_better_than_reference": float((resampled < 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def departure_table(
    prepared: Frames, candidates: dict[str, Candidate], split: str = "test"
) -> pd.DataFrame:
    """For each candidate, how far its prediction is from a base rate times relativities."""
    frame = getattr(prepared, split)
    matrix = glm.design_matrix(frame, FACTORS, rating=True)
    rows = [
        {"candidate": name, **multiplicative_departure(c.unit_prediction(split), matrix)}
        for name, c in candidates.items()
    ]
    return pd.DataFrame(rows)


def overall_ae_interval(
    frame: pd.DataFrame,
    candidates: dict[str, Candidate],
    split: str = "test",
    n_boot: int = 2000,
    seed: int = 20221102,
) -> pd.DataFrame:
    """Overall A/E with a 95 percent interval from resampling households."""
    rng = np.random.default_rng(seed)
    households = pd.factorize(frame["DUID"])[0]
    count = households.max() + 1
    draws = rng.integers(0, count, size=(n_boot, count))
    actual = np.bincount(households, weights=frame["cost"].to_numpy(), minlength=count)
    rows = []
    for name, candidate in candidates.items():
        expected = np.bincount(households, weights=candidate.prediction(split), minlength=count)
        ratio = actual[draws].sum(axis=1) / expected[draws].sum(axis=1)
        rows.append(
            {
                "candidate": name,
                "a_e": float(actual.sum() / expected.sum()),
                "lower_95": float(np.quantile(ratio, 0.025)),
                "upper_95": float(np.quantile(ratio, 0.975)),
            }
        )
    return pd.DataFrame(rows)
