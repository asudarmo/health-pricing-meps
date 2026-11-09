"""The recalibration rule read at segment level, from a published table (issue #74).

`outputs/<version>/ae_intervals.csv` holds the 2023 A/E of each rating level with its 95 percent
interval, and the same A/E relative to the book. The rule of `_docs/recalibration-rule.md` reads two
signs. A level has a gap when its interval excludes 1. A level is off the book when its relative A/E
interval excludes 1. A gap alone is a level shift, which a rebase answers. A level off the book is a
change in shape, which a refit answers. Levels with under 30 claimants are not read. This module
holds pandas only, so the service image can use it.
"""

from __future__ import annotations

import pandas as pd

LEVEL_SHIFT = "level shift"
CHANGE_IN_SHAPE = "change in shape"


def segment_flags(intervals: pd.DataFrame) -> list[dict]:
    """The flagged segments: segment, a_e, exposure, gap_type and a note."""
    flags = []
    for row in intervals[intervals["enough_claimants"]].itertuples():
        gap = row.lower_95 > 1 or row.upper_95 < 1
        off_book = row.relative_lower_95 > 1 or row.relative_upper_95 < 1
        if not (gap or off_book):
            continue
        segment = "all" if row.factor == "all" else f"{row.factor} {row.level}"
        interval = f"{row.lower_95:.3f} to {row.upper_95:.3f}"
        if off_book:
            kind = CHANGE_IN_SHAPE
            note = (
                f"A/E {row.a_e:.3f} is {row.relative_a_e:.3f} of the book, and the interval of the "
                f"relative A/E excludes 1."
            )
        else:
            kind = LEVEL_SHIFT
            note = f"A/E {row.a_e:.3f} with an interval of {interval} excludes 1, as the book does."
        flags.append(
            {
                "segment": segment,
                "a_e": float(row.a_e),
                "exposure": float(row.exposure),
                "gap_type": kind,
                "note": note,
            }
        )
    return flags
