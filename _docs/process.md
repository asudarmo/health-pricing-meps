# Process

- Tasks live in GitHub issues once the repo exists (until then, in `_docs/tasks.md`). One task at a time.
- Tasks are numbered in creation order and each belongs to one milestone (M1–M9, `_docs/plan.md` section 5).
  In GitHub, assign each issue to the matching GitHub milestone and label decision-gate tasks `decision-gate`.
- Work milestone by milestone, respecting the "Depends on" column. If time is short, follow the plan's cut order.
- Each task is small enough for one session and follows `_docs/task-template.md`.
- Read the acceptance criteria before starting and before closing a task.
- Commit regularly. End each session with an entry in `_docs/log.md`.
- If a task reaches a decision gate (`AGENTS.md`), stop and ask the user.

## Roles

- PM - grooms a task before anyone implements it, follows `_docs/team/pm.md`
- Engineer - implements one groomed task, follows `_docs/team/software-engineer.md`
- QA - checks the result against the acceptance criteria, follows `_docs/team/qa-engineer.md`

## Lifecycle

1. Pick the next open task
2. PM grooms it (skip only if it is already groomed)
3. Engineer implements it
4. QA verifies it in a fresh session or subagent
5. On FAIL, back to step 3 with the QA comment as input
6. On PASS, close the task
7. Repeat. Stop at any decision gate, and at the end of each milestone for the user's review

## Rules

- The engineer does not close tasks
- QA does not fix code, only outputs PASS or FAIL
- A task is closed only after QA outputs PASS
