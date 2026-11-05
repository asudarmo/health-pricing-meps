# Process

## Tasks

- Tasks live in GitHub issues, one at a time. Each belongs to one milestone (M1 to M10, `_docs/plan.md`
  section 5). Label decision-gate tasks `decision-gate` and optional tasks `optional`.
- Work milestone by milestone, respecting the "Depends on" column and the delivery scope in `_docs/plan.md`.
  If time or tokens are short, follow the plan's cut order.
- Each task is small enough for one session and follows `_docs/task-template.md`. The engineer writes or
  tightens the task's acceptance criteria before starting. There is no separate grooming role.
- Acceptance criteria must be bounded. Name the exact items, or the exact test or dbt check that covers
  them. Avoid open-ended wording such as "confirmed for each variable".
- Commit regularly. End each session with an entry in `_docs/log.md`.
- If a task reaches a decision gate (`AGENTS.md`), stop and ask the user.

## Roles

- Engineer: writes the task's criteria if needed, implements it and tests it, following
  `_docs/team/software-engineer.md`.
- QA (lite): checks the result against the acceptance criteria in a fresh session or subagent, following
  `_docs/team/qa-engineer.md`. Used only where the QA scope below requires it.

The PM role (`_docs/team/pm.md`) is no longer used (since 3 Nov 2026).

## Lifecycle

1. Pick the next open task and check its acceptance criteria
2. Engineer implements it, with tests
3. If the task is in QA scope, QA verifies it. On FAIL, back to step 2 with the QA comment as input. After
   two FAIL rounds, stop and escalate to the user, who decides whether to accept, rescope or split it
4. Otherwise, the engineer records a self-check against the criteria in a comment on the task
5. Close the task
6. Repeat. Stop at any decision gate, and at the end of each milestone for the user's review

## QA scope (lite)

- QA runs for decision-gate tasks, modelling tasks that change model outputs, data-validation tasks, and any
  task the user flags. One QA pass per task by default.
- Everything else (setup, documentation, notebooks, refactoring, serving and app plumbing) gets the
  engineer's tests plus a recorded self-check, with no separate QA pass.
- Style and grammar notes are non-blocking. They never cause a FAIL or another QA round. Only the automated
  writing-style test (em dashes, semicolons) counts.
- QA does not fix code, only outputs PASS or FAIL.

## Token-saving tactics

- Start a fresh session for each task or small group of related tasks. Long sessions re-read a lot of context.
- Keep reports short: what changed, the test summary line, and anything the user must decide, in under 150
  words.
- Run targeted tests while working. Run the full suite once at the end of a milestone or once a day, not after
  every task. The full suite executes all notebooks and is slow.
- Do not re-execute notebooks for text-only changes. Edit Markdown cells and run only the writing-style and
  notebook-structure tests.
- Read only the files a task needs. Prefer `grep` and targeted reads over opening whole notebooks or large
  files.
- Do not re-verify closed tasks. A status check means reading issue states and closing comments, not
  re-running their checks.
- Ask before starting work that is not in the current delivery scope (`_docs/plan.md`).
