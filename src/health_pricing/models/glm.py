"""Two-part GLM candidates (a) and (b), and the scoring shared by every candidate (issues #28, #29).

Each candidate predicts the expected annual PMI-scope cost of a person-year at 2023 prices. A
frequency GLM gives the expected claimants of the person-year, with `log(exposure)` as an offset.
A Gamma severity GLM gives the expected capped cost per claimant. The prediction is their product,
plus the provisional large-claim load. The claim count is never used. The target is whether the
capped annual cost is above zero, and the cost per claimant is the capped annual cost.

- Candidate (a) uses a binomial GLM with a cloglog link, so the claimant probability is
  `1 - exp(-exposure * exp(eta))` and cannot exceed 1.
- Candidate (b) uses a Poisson GLM on the same indicator, so the expected claimants can exceed 1.

Fitting uses only the train frame, unweighted. The `unknown` level of the smoking and exercise
questions is fitted as a control and priced at the reference level when predicting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.genmod.families import links

from health_pricing.models import large_claims, levels, metrics
from health_pricing.models.frame import FACTORS, Frames

FREQUENCY_LINKS = ("cloglog", "poisson")
SCORES_DIR = Path(__file__).resolve().parents[3] / "outputs" / "m3_draft"
SCORE_COLUMNS = [
    "candidate", "split", "tweedie_deviance", "mean_tweedie_deviance", "tweedie_deviance_p1_3",
    "tweedie_deviance_p1_7", "gini", "a_e", "parameters", "dropped_reason",
]  # fmt: skip


def prepare_frames(frames: Frames) -> Frames:
    """Frames with the approved level grouping and the large-claim cap, ready to fit.

    The factors are recoded with the reference group first, and `capped_cost` is the annual cost
    limited to the cap. The `cost` column is the uncapped cost the models are scored against.
    """
    capped = large_claims.cap_frames(frames)
    return levels.apply_grouping(capped, levels.decided_grouping(frames))


def design_matrix(
    frame: pd.DataFrame,
    factors: list[str] = FACTORS,
    rating: bool = False,
    interaction: tuple[str, str] | None = None,
    numeric: tuple[str, ...] = (),
) -> pd.DataFrame:
    """A constant, then a 0/1 column for each non-reference level of each factor.

    The `unknown` level of the smoking and exercise questions becomes one `unknown_control` column
    that is 1 for those person-years when fitting and 0 when `rating` is set, so they are priced at
    the reference. `interaction` names two factors whose level pairs are added as extra columns,
    and `numeric` names frame columns that are added as they are, for example spline terms.
    """
    data = frame[list(factors)].copy()
    kept = [factor for factor in levels.KEEP_UNKNOWN if factor in data]
    # the same people are `unknown` on both questions, so they share one control column
    control = np.zeros(len(data))
    for factor in kept:
        control = np.maximum(control, (data[factor] == levels.UNKNOWN_LEVEL).to_numpy())
        categories = list(data[factor].cat.categories)
        column = data[factor].astype(object).replace(levels.UNKNOWN_LEVEL, categories[0])
        data[factor] = pd.Categorical(column, categories=categories)
    matrix = pd.get_dummies(data, drop_first=True, prefix_sep="=", dtype=float)
    if kept:
        matrix = matrix.drop(columns=[f"{f}={levels.UNKNOWN_LEVEL}" for f in kept], errors="ignore")
        matrix["unknown_control"] = 0.0 if rating else control
    if interaction:
        first, second = (
            pd.get_dummies(data[[name]], drop_first=True, prefix_sep="=", dtype=float)
            for name in interaction
        )
        for a in first:
            for b in second:
                matrix[f"{a}:{b}"] = first[a] * second[b]
    for column in numeric:
        matrix[column] = frame[column].to_numpy(dtype=float)
    matrix.insert(0, "const", 1.0)
    return matrix


def _check_rank(matrix: pd.DataFrame) -> None:
    rank = np.linalg.matrix_rank(matrix.to_numpy())
    if rank < matrix.shape[1]:
        raise ValueError(f"design matrix has rank {rank} for {matrix.shape[1]} columns")


def _fit_options(groups) -> dict:
    return {} if groups is None else {"cov_type": "cluster", "cov_kwds": {"groups": groups}}


@dataclass
class TwoPartModel:
    name: str
    link: str
    factors: list[str]
    interaction: tuple[str, str] | None
    interaction_parts: tuple[str, ...]
    frequency_columns: list[str]
    severity_columns: list[str]
    frequency: object
    severity: object
    numeric: tuple[str, ...] = ()

    def _matrix(self, frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        matrix = design_matrix(
            frame, self.factors, rating=True, interaction=self.interaction, numeric=self.numeric
        )
        return matrix.reindex(columns=columns, fill_value=0.0)

    def expected_claimants(self, frame: pd.DataFrame) -> np.ndarray:
        """A probability for cloglog, and the expected number of claimants for Poisson."""
        matrix = self._matrix(frame, self.frequency_columns)
        offset = np.log(frame["exposure"].to_numpy())
        return np.asarray(self.frequency.predict(matrix, offset=offset))

    def expected_severity(self, frame: pd.DataFrame) -> np.ndarray:
        """Expected capped cost per claimant."""
        return np.asarray(self.severity.predict(self._matrix(frame, self.severity_columns)))

    def predict_capped(self, frame: pd.DataFrame) -> np.ndarray:
        """Expected claimants times expected severity, before the large-claim load."""
        return self.expected_claimants(frame) * self.expected_severity(frame)

    def predict(self, frame: pd.DataFrame, load: float = large_claims.PROVISIONAL_LOAD):
        """Expected annual cost per person-year, with the large-claim load."""
        return large_claims.with_load(self.predict_capped(frame), load)

    @property
    def parameters(self) -> int:
        return len(self.frequency.params) + len(self.severity.params)

    @property
    def dispersion(self) -> float:
        """The Gamma dispersion of the severity model."""
        return float(self.severity.scale)


def fit_two_part(
    frame: pd.DataFrame,
    link: str,
    factors: list[str] = FACTORS,
    name: str = "",
    interaction: tuple[str, str] | None = None,
    groups=None,
    interaction_parts: tuple[str, ...] = ("frequency", "severity"),
    numeric: tuple[str, ...] = (),
) -> TwoPartModel:
    """Fit a frequency GLM and a Gamma severity GLM on a train frame.

    `frame` needs `exposure`, `capped_cost` and the factor columns. `groups` gives a cluster for
    each row, and the standard errors are then clustered. `interaction_parts` says which parts
    carry the interaction columns, if there is an interaction, and `numeric` names frame columns
    that enter as they are, such as spline terms. Nothing else in the frame is read,
    so a claim count cannot enter as a weight or a predictor.
    """
    if link not in FREQUENCY_LINKS:
        raise ValueError(f"link must be one of {FREQUENCY_LINKS}")
    groups = None if groups is None else np.asarray(groups)
    claimed = (frame["capped_cost"] > 0).to_numpy()
    matrix = design_matrix(frame, factors, interaction=interaction, numeric=numeric)
    # a column with no claimants, or no rows, cannot be estimated
    freq_columns = [c for c in matrix if c == "const" or matrix[c].any()]
    sev_columns = [c for c in matrix if c == "const" or matrix.loc[claimed, c].any()]
    if "frequency" not in interaction_parts:
        freq_columns = [c for c in freq_columns if ":" not in c]
    if "severity" not in interaction_parts:
        sev_columns = [c for c in sev_columns if ":" not in c]
    for columns, rows in ((freq_columns, slice(None)), (sev_columns, claimed)):
        _check_rank(matrix.loc[rows, columns])
    family = (
        sm.families.Binomial(link=links.CLogLog()) if link == "cloglog" else sm.families.Poisson()
    )
    frequency = sm.GLM(
        claimed.astype(float),
        matrix[freq_columns],
        family=family,
        offset=np.log(frame["exposure"].to_numpy()),
    ).fit(**_fit_options(groups))
    severity = sm.GLM(
        frame.loc[claimed, "capped_cost"].to_numpy(),
        matrix.loc[claimed, sev_columns],
        family=sm.families.Gamma(link=links.Log()),
    ).fit(**_fit_options(None if groups is None else groups[claimed]))
    return TwoPartModel(
        name,
        link,
        list(factors),
        interaction,
        tuple(interaction_parts),
        freq_columns,
        sev_columns,
        frequency,
        severity,
        tuple(numeric),
    )


def coefficient_table(model: TwoPartModel, frame: pd.DataFrame) -> pd.DataFrame:
    """Coefficients and standard errors of both parts, with claimants in every level.

    `frame` is the frame the model was fitted on. A claimant here is a person-year with a positive
    capped cost. The constant row carries all claimants.
    """
    claimed = frame["capped_cost"] > 0
    matrix = design_matrix(
        frame, model.factors, interaction=model.interaction, numeric=model.numeric
    )
    rows = []
    for part, result in (("frequency", model.frequency), ("severity", model.severity)):
        for term, estimate in result.params.items():
            rows.append(
                {
                    "part": part,
                    "term": term,
                    "coefficient": estimate,
                    "std_error": result.bse[term],
                    "relativity": float(np.exp(estimate)),
                    "claimants": int(
                        claimed.sum() if term == "const" else matrix.loc[claimed, term].sum()
                    ),
                }
            )
    return pd.DataFrame(rows)


def deviance_test(restricted: TwoPartModel, full: TwoPartModel, part: str) -> dict[str, float]:
    """Likelihood-ratio style test of a restricted model against a fuller one for one part.

    The statistic is the fall in deviance divided by the dispersion of the fuller model, which is 1
    for the frequency part. It is compared with a chi-squared distribution.
    """
    small, large = getattr(restricted, part), getattr(full, part)
    df = large.df_model - small.df_model
    statistic = (small.deviance - large.deviance) / large.scale
    return {
        "part": part,
        "statistic": float(statistic),
        "df": float(df),
        "p_value": float(stats.chi2.sf(statistic, df)),
    }


def probability_calibration(claimed, probability, n: int = 10) -> pd.DataFrame:
    """Observed claimant rate against the mean predicted claimants, by decile of prediction."""
    frame = pd.DataFrame(
        {"claimed": np.asarray(claimed, dtype=float), "predicted": np.asarray(probability)}
    )
    ones = pd.Series(1.0, index=frame.index)
    frame["group"] = metrics._buckets(frame["predicted"], ones, n)
    table = frame.groupby("group").agg(
        person_years=("claimed", "size"),
        observed_rate=("claimed", "mean"),
        mean_predicted=("predicted", "mean"),
    )
    table["observed_over_predicted"] = table["observed_rate"] / table["mean_predicted"]
    return table.reset_index()


def candidate_scores(
    candidate: str, parameters: int, splits: dict[str, tuple[pd.DataFrame, np.ndarray]]
) -> pd.DataFrame:
    """The shared scores on each split, in the columns of the model comparison table.

    `splits` maps a split name to its person-year frame and the predicted annual cost. Actual cost
    is the uncapped `cost` column, so the load is part of what is scored.
    """
    rows = []
    for name, (frame, predicted) in splits.items():
        scores = metrics.score(frame, predicted)
        by_power = metrics.deviance_by_power(frame["cost"], predicted)
        rows.append(
            {
                "candidate": candidate,
                "split": name,
                "tweedie_deviance": scores["tweedie_deviance"],
                "mean_tweedie_deviance": scores["mean_tweedie_deviance"],
                "tweedie_deviance_p1_3": by_power[1.3],
                "tweedie_deviance_p1_7": by_power[1.7],
                "gini": scores["gini"],
                "a_e": scores["a_e"],
                "parameters": parameters,
                "dropped_reason": "",
            }
        )
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


def save_scores(scores: pd.DataFrame, name: str, directory: Path = SCORES_DIR) -> Path:
    """Save one candidate's scores for the comparison. The table holds aggregates only."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"scores_candidate_{name}.csv"
    scores.to_csv(path, index=False)
    return path


def wide_coefficients(table: pd.DataFrame) -> pd.DataFrame:
    """The long coefficient table with the frequency and severity parts side by side.

    Terms keep the order of the design matrix. A term missing from one part is left empty.
    """
    parts = {part: rows.set_index("term") for part, rows in table.groupby("part", sort=False)}
    order = list(dict.fromkeys(table["term"]))
    wide = pd.concat(
        {
            part: rows[["coefficient", "std_error", "relativity", "claimants"]]
            for part, rows in parts.items()
        },
        axis=1,
    )
    return wide.reindex(order).rename_axis("term")
