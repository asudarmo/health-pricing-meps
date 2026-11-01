# AGENTS.md

UK-style private medical insurance (PMI) pricing models built on US MEPS survey data: data pipeline and
validation, frequency/severity GLMs, a gradient-boosting challenger, A/E and drift monitoring, rate-change
impact, conversion/elasticity, and an Excel-to-Python reconciliation. The full plan is `_docs/plan.md`.
Read it before starting any task.

Audience for all outputs: an actuarial pricing reviewer. Write in plain British English, following `_docs/writing-style.md`.

## Commands

To be confirmed and updated by Task 1. Keep this section accurate.

- `uv sync` - install dependencies
- `uv run pytest` - the whole test suite
- `uv run pytest tests/test_<name>.py` - one test file
- `uv run python -m health_pricing.data.download` - download the MEPS raw files (data/raw/)
- `uv run python -m health_pricing.data.load` - load the raw files into DuckDB (data/interim/)
- `uv run dbt deps --project-dir dbt --profiles-dir dbt` - install the dbt package (`dbt_utils`), once per clone
- `uv run dbt build --project-dir dbt --profiles-dir dbt` - build and test the dbt models
- `uv run python -m health_pricing.data_dictionary` - regenerate `_docs/data-dictionary.md` from the dbt marts `schema.yml`
- `uv run ruff check . && uv run ruff format --check .` - lint and format check
- `uv run jupyter lab` - notebooks

## Structure

- `src/health_pricing/` - installable pricing package: data loading, validation, features, models, rating
  engine, monitoring, scenario impact. All reusable logic lives here.
- `dbt/` - DuckDB staging and modelling-table SQL, with dbt tests.
- `notebooks/` - numbered notebooks (`01_data.ipynb`, `02_eda.ipynb`, ...) that explain each modelling
  step for a reviewer. Notebooks import from the package. They do not define reusable logic.
- `data/raw/` - downloaded MEPS files. Git-ignored. Never committed.
- `data/interim/` - DuckDB database and intermediate files. Git-ignored.
- `outputs/<model_version>/` - published, versioned, aggregated tables (see `_docs/plan.md` section 6).
- `tests/` - pytest.
- `_docs/` - plan, process, decisions, log, team roles.

## Rules

- Never commit raw or person-level MEPS data. Published outputs are aggregated only.
- MEPS data use: statistical analysis only, no attempt to identify individuals, cite AHRQ/MEPS as source.
- Do not add a dependency without asking.
- Downloads are scripted (URL + expected file size or checksum), so the pipeline is reproducible.
- Set random seeds. Results must be reproducible from a clean clone plus the download script.
- Every modelling or data choice goes in `_docs/decisions.md` (date, decision, why, alternatives).
- At the end of each session, add a short entry to `_docs/log.md`: what was done, what is next, open questions.
- Commit after each meaningful step with a clear message.
- The final rating structure uses only permitted UK rating factors. It excludes sex, race, income and
  education (sex may be analysed, and the impact of excluding it shown).
- All prose (README, notebook text, model documentation, chart text, `AGENTS.md` and everything in
  `_docs/`) follows `_docs/writing-style.md`. Read it before writing or editing any of these.

## Decision gates: STOP and ask the user

Do not decide these alone. Present the evidence and options, recommend one, and wait:

1. The MEPS variable shortlist and the 2022↔2023 variable-name mapping
2. The PMI-scope claim definition (which event types and providers count as claims), especially if
   office-based events cannot be split by provider specialty
3. Exclusion rules that remove more than 1% of persons or of total cost
4. The price index used to on-level 2022 costs, and the assumed frequency trend
5. Large-claim threshold and treatment
6. Grouping of rating-factor levels (e.g. age bands) in the final GLMs
7. GLM vs GBM model choice, and the final rating structure
8. Any change to the plan's scope or the published output contract (section 6)

Pre-approved patterns (no gate needed, log each use in `_docs/decisions.md`):

- A person-level characteristic whose year-end value is -1 because the person left the survey part-way
  takes the latest valid round value, with a `_source` flag (as done for `age` and `region`). A question
  asked in the last round only keeps an `unknown` level instead.
- `left_survey_early` marks those people for analysis only. It must never be used as a rating factor.

## Verification

- Reconcile the data layer to published figures: person counts against the MEPS documentation, and weighted
  totals/means (e.g. mean total expenditure) against AHRQ's published MEPS summary tables for the same year.
- Every task's acceptance criteria are checked by a separate QA pass (see `_docs/process.md`), not by the
  session that wrote the code.

## Documents

- `_docs/plan.md` - the project plan (source of truth for scope)
- `_docs/process.md` - how work is organised (read at the start of every session)
- `_docs/task-template.md` - template for groomed tasks
- `_docs/writing-style.md` - writing rules for all prose (read before writing any text for people)
- `_docs/decisions.md` - decision log
- `_docs/log.md` - session log
- `_docs/team/` - role definitions (PM, engineer, QA)
