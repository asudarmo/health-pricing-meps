# Session log

Newest at the bottom. Each entry: date, what was done, what is next, open questions.

## 2026-10-31 Repo setup and tooling (M1)

Done: initialised git, created the public GitHub repo `asudarmo/health-pricing-meps`, and built the
repo skeleton. uv-managed Python package at `src/health_pricing`, pytest, ruff (lint and format),
a dbt+DuckDB scaffold under `dbt/` (verified with `dbt debug`), a writing-style check test
(`tests/test_writing_style.py`), and a GitHub Actions CI workflow. Created GitHub milestones M1-M9
and the seven M1 issues (#1-#7), with #3 labelled `decision-gate`. Issues #1 and #2 are implemented
as part of this session but not yet closed, because QA has not verified them (per `_docs/process.md`,
the engineer does not close tasks).

Next: issue #3, the MEPS variable shortlist and 2022-23 name mapping. This is decision gate 1 and
needs the user's review before anything downstream uses it.

Open questions: none beyond the decision gate itself.
