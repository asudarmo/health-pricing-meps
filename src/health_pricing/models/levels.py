"""Levels of the rating factor candidates and how they are grouped (issue #26, decision gate 6).

The evidence tables describe each level on the 2022 train split. `build_grouping` turns a set of
rules into a map from every value in the data to one group, and `apply_grouping` recodes the
train and test frames with it. The user approved the rules at decision gate 6 on 2026-11-02 and
`decided_grouping` applies them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from health_pricing.models import leakage
from health_pricing.models.frame import FACTORS, Frames, _as_text, _level_key

THIN_CLAIMANTS = 30
MISSING = "missing"
CHILD_LEVEL = "not_applicable"
UNKNOWN_LEVEL = "unknown"
PLACEHOLDERS = (CHILD_LEVEL, UNKNOWN_LEVEL, MISSING)
# The leakage check (issue #25) found `unknown` is a leaver marker for these two questions. The
# level stays in the fit as a control and is priced at the reference. Elsewhere it merges. Gate 6
# set the test: keep it where merging would move the reference cost by more than 2%. Only these
# two do, and `unknown_rule_table` shows the figure for every variable.
KEEP_UNKNOWN = ("OFTSMK53", "PHYEXE53")
UNKNOWN_CONTROL_LIMIT = 0.02
AGE_OPTION = "five_year"  # approved at gate 6
LEVEL_GROUPING_PATH = (
    Path(__file__).resolve().parents[3] / "outputs" / "m3_draft" / "level_grouping.csv"
)

TOP_AGE = 85  # AHRQ caps age at 85, so the last band is open ended

AGE_BANDS = {
    "five_year": [
        (0, 4), (5, 14), (15, 17), (18, 24), (25, 29), (30, 34), (35, 39), (40, 44), (45, 49),
        (50, 54), (55, 59), (60, 64), (65, 69), (70, 74), (75, 79), (80, TOP_AGE),
    ],
    "ten_year": [
        (0, 4), (5, 14), (15, 17), (18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 74),
        (75, TOP_AGE),
    ],
}  # fmt: skip


def age_label(age: int, bands: list[tuple[int, int]]) -> str:
    """The band an age falls in, as `00-04` or `80+` for the open top band."""
    for low, high in bands:
        if low <= age <= high:
            return f"{low}+" if high == TOP_AGE else f"{low:02d}-{high:02d}"
    raise ValueError(f"age {age} is outside the bands")


def level_series(frame: pd.DataFrame, factor: str) -> pd.Series:
    """A factor's levels as text, with a null answer shown as `missing`."""
    return _as_text(frame[factor].astype("object")).fillna(MISSING)


def level_evidence(frame: pd.DataFrame, factors: list[str] = FACTORS) -> pd.DataFrame:
    """Person-years, exposure, claimants and claims for each level, with a thin-level flag."""
    rows = []
    for factor in factors:
        grouped = frame.groupby(level_series(frame, factor))
        table = grouped.agg(
            person_years=("exposure", "size"),
            exposure=("exposure", "sum"),
            claimants=("claimant", "sum"),
            claims=("claim_count", "sum"),
            cost=("cost", "sum"),
        )
        table["claimant_rate"] = table["claimants"] / table["person_years"]
        table["cost_per_exposure_year"] = table["cost"] / table["exposure"]
        table["thin"] = table["claimants"] < THIN_CLAIMANTS
        table = table.loc[sorted(table.index, key=_sort_key)].drop(columns="cost")
        table = table.reset_index(names="level")
        table.insert(0, "factor", factor)
        rows.append(table)
    return pd.concat(rows, ignore_index=True)


def _sort_key(level: str):
    return (level in PLACEHOLDERS, _level_key(level))


def age_band_table(frame: pd.DataFrame, bands: list[tuple[int, int]]) -> pd.DataFrame:
    """Person-years, claimants, claimant rate and cost per exposure year for each age band."""
    age = frame["age"].astype(int)
    labelled = frame.assign(band=age.map(lambda a: age_label(a, bands)))
    table = labelled.groupby("band").agg(
        person_years=("exposure", "size"),
        exposure=("exposure", "sum"),
        claimants=("claimant", "sum"),
        cost=("cost", "sum"),
    )
    table["claimant_rate"] = table["claimants"] / table["person_years"]
    table["cost_per_exposure_year"] = table["cost"] / table["exposure"]
    table["thin"] = table["claimants"] < THIN_CLAIMANTS
    return table.drop(columns="cost").reset_index()


@dataclass
class Grouping:
    mapping: dict[str, dict[str, str]]  # factor -> level -> group
    reference: dict[str, str]  # factor -> reference group

    def table(self) -> pd.DataFrame:
        """The map as a table with one row per factor and level, flagging the reference group."""
        rows = [
            {
                "factor": f,
                "level": level,
                "group": group,
                "reference": group == self.reference[f],
            }
            for f, levels in self.mapping.items()
            for level, group in levels.items()
        ]
        return pd.DataFrame(rows)


def _reference_level(frame: pd.DataFrame, factor: str) -> str:
    """The real answer with the most exposure, never a placeholder."""
    levels = level_series(frame, factor)
    exposure = frame["exposure"].groupby(levels).sum()
    exposure = exposure.drop([p for p in PLACEHOLDERS if p in exposure.index])
    return sorted(exposure.items(), key=lambda item: (-item[1], _level_key(item[0])))[0][0]


def build_grouping(frames: Frames, age_bands: list[tuple[int, int]]) -> Grouping:
    """Group every level present in train or test, using the rules and train claimant counts.

    - Age is banded.
    - `not_applicable` (a child on an adult question) and `missing` (refused, don't know or
      cannot be computed) merge into the reference level.
    - `unknown` stays a level for the factors in KEEP_UNKNOWN and merges into the reference
      elsewhere.
    - Any other level with fewer than THIN_CLAIMANTS train claimants merges into the reference.
    """
    both = pd.concat([frames.train, frames.test], ignore_index=True)
    mapping, reference = {}, {}
    for factor in FACTORS:
        levels = level_series(both, factor)
        if factor == "age":
            groups = {level: age_label(int(level), age_bands) for level in sorted(set(levels))}
            exposure = both["exposure"].groupby(levels.map(groups)).sum()
            reference[factor] = sorted(exposure.items(), key=lambda i: (-i[1], i[0]))[0][0]
            mapping[factor] = groups
            continue
        ref = _reference_level(frames.train, factor)
        claimants = frames.train["claimant"].groupby(level_series(frames.train, factor)).sum()
        groups = {}
        for level in sorted(set(levels), key=_sort_key):
            thin = claimants.get(level, 0) < THIN_CLAIMANTS
            if level == CHILD_LEVEL or level == MISSING:
                groups[level] = ref
            elif level == UNKNOWN_LEVEL:
                keep = factor in KEEP_UNKNOWN and not thin
                groups[level] = UNKNOWN_LEVEL if keep else ref
            else:
                groups[level] = ref if thin else level
        reference[factor], mapping[factor] = ref, groups
    return Grouping(mapping, reference)


def _group_column(frame: pd.DataFrame, factor: str, grouping: Grouping) -> pd.Series:
    levels = level_series(frame, factor)
    unmapped = sorted(set(levels) - set(grouping.mapping[factor]))
    if unmapped:
        raise KeyError(f"{factor} has levels with no group: {unmapped}")
    return levels.map(grouping.mapping[factor])


def apply_grouping(frames: Frames, grouping: Grouping) -> Frames:
    """Recode the factors of the train and test frames, with the reference group first."""
    both = pd.concat([frames.train, frames.test], ignore_index=True)
    categories = {}
    for factor in FACTORS:
        groups = set(grouping.mapping[factor].values())
        others = sorted(groups - {grouping.reference[factor]}, key=_sort_key)
        categories[factor] = [grouping.reference[factor], *others]
        assert set(_group_column(both, factor, grouping)) <= groups

    def recode(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        for factor in FACTORS:
            column = _group_column(frame, factor, grouping)
            frame[factor] = pd.Categorical(column, categories=categories[factor])
        return frame

    return Frames(recode(frames.train), recode(frames.test), dict(grouping.reference))


def grouping_summary(frames: Frames, grouping: Grouping) -> pd.DataFrame:
    """For each factor and group, the levels merged into it with train exposure and claimants."""
    rows = []
    train = frames.train
    for factor in FACTORS:
        groups = _group_column(train, factor, grouping)
        grouped = train.groupby(groups)
        merged = {
            g: ", ".join(sorted((lv for lv, gr in grouping.mapping[factor].items() if gr == g),
                                key=_sort_key))
            for g in set(grouping.mapping[factor].values())
        }  # fmt: skip
        for group, rows_in_group in grouped:
            rows.append(
                {
                    "factor": factor,
                    "group": group,
                    "reference": group == grouping.reference[factor],
                    "levels_merged": merged[group] if factor != "age" else "",
                    "person_years": len(rows_in_group),
                    "exposure": rows_in_group["exposure"].sum(),
                    "claimants": int(rows_in_group["claimant"].sum()),
                }
            )
    return pd.DataFrame(rows)


def decided_grouping(frames: Frames) -> Grouping:
    """The grouping approved at gate 6: five-year age bands and the rules in `build_grouping`."""
    return build_grouping(frames, AGE_BANDS[AGE_OPTION])


def save_grouping(grouping: Grouping, path: Path = LEVEL_GROUPING_PATH) -> Path:
    """Write the level map (no person-level data, one row per factor and level) as a csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    grouping.table().to_csv(path, index=False)
    return path


def presentation_age_reference(frames: Frames, grouping: Grouping) -> str:
    """The adult age band with the most train exposure, for showing age relativities.

    The technical reference (`grouping.reference["age"]`) stays the band with the most exposure
    overall. Rebasing changes only how relativities are shown, not the fitted model.
    """
    ages = frames.train["age"].astype(int)
    adult = ages >= leakage.ADULT_AGE
    bands = ages[adult].astype(str).map(grouping.mapping["age"])
    exposure = frames.train.loc[adult, "exposure"].groupby(bands).sum()
    return sorted(exposure.items(), key=lambda item: (-item[1], item[0]))[0][0]


def unknown_rule_table(
    frame: pd.DataFrame | None = None, variables: list[str] = leakage.UNKNOWN_VARIABLES
) -> pd.DataFrame:
    """For each variable with an `unknown` level, the reference cost change if it were merged.

    `frame` is the adult train frame from `leakage.load_leakage_frame`. `exceeds_limit` is the
    gate 6 test and `kept_as_control` is the rule in force, so the two should agree.
    """
    frame = leakage.load_leakage_frame() if frame is None else frame
    table = leakage.merge_effect_table(frame, variables)
    table["exceeds_limit"] = table["change_after_merge"].abs() > UNKNOWN_CONTROL_LIMIT
    table["kept_as_control"] = table["variable"].isin(KEEP_UNKNOWN)
    return table


def inscov_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Each `inscov` level: size, claimant rate, cost, age mix, and share of the frame's totals."""
    age = frame["age"].astype(int)
    work = frame.assign(over_65=age >= 65, under_18=age < 18, age_years=age)
    table = work.groupby(level_series(work, "inscov")).agg(
        person_years=("exposure", "size"),
        exposure=("exposure", "sum"),
        claimants=("claimant", "sum"),
        cost=("cost", "sum"),
        mean_age=("age_years", "mean"),
        share_over_65=("over_65", "mean"),
        share_under_18=("under_18", "mean"),
    )
    table["claimant_rate"] = table["claimants"] / table["person_years"]
    table["cost_per_exposure_year"] = table["cost"] / table["exposure"]
    for column in ("person_years", "exposure", "claimants", "cost"):
        table[f"{column}_share"] = table[column] / table[column].sum()
    return table.drop(columns="cost").reset_index(names="level")
