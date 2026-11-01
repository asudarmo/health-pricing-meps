# Writing style

## Scope

This guide applies to all prose written for people to read.

- README and any other Markdown in the repo
- Notebook text (Markdown cells)
- Model documentation and reports
- Chart titles, axis labels and captions
- `AGENTS.md` and everything in `_docs/` (plan, process, tasks, decisions, log, team roles, templates)
- GitHub issues, comments and pull request descriptions

Code, code comments, docstrings, URLs and file paths are exempt, but keep comments plain.

## How strictly to apply this guide

- Only the em dash and semicolon rules are enforced, by the automated test below. Everything else is
  guidance, not a pass/fail rule.
- Aim for clear, plain British English. Do not nit-pick grammar (comma splices, sentence fragments, Oxford
  commas, minor wording) and do not rewrite text only to polish it.
- Follow the guide for text you write or change in the current task. Do not restyle existing text the task
  does not otherwise touch.
- The careful style review of reader-facing documents (README, notebooks, model documentation) happens
  once, in M9 (write-up), not on every task.

## Rules

1. Write plain British English (organise, modelling, utilisation). Prefer short sentences. Write for an
   actuarial pricing reviewer.
2. Never use an em dash (—).
3. Use an en dash (–) only for ranges, such as 2022–23, M1–M9 or 3–5 years. Never use a spaced en dash
   ( – ) as a clause break.
4. Never use a colon or a semicolon to join two clauses. Write two sentences instead, or join the clauses
   with a word such as "and", "but", "so" or "because".
5. Do not use semicolons in prose at all. In table cells, separate list items with " · ".

Colons are still fine in these cases.

- To introduce a list, either inline ("Tools: Python, SQL, pytest") or before bullet points
- In labels at the start of a line or a bullet, such as "Source: AHRQ" or "**Frequency:** Poisson GLM"
- In ratios and times, such as 3:1 or 09:30
- In code, URLs and file paths

## Examples

| Before | After |
|---|---|
| Severity is volatile; we cap large claims. | Severity is volatile, so we cap large claims. |
| Two years is short — but realistic for health. | Two years is short, but it is realistic for health. |
| The answer is clear: the age curve is stable. | The answer is clear. The age curve is stable. |
| Exclude 2020–21; COVID distorted utilisation. | Exclude 2020–21 because COVID distorted utilisation. |
| Deliverables: tests; charts; a README | Deliverables: tests · charts · a README (in a table cell), or a bulleted list in prose |

## Checking

Before finishing any prose, search it for "—", ";" and for a colon followed by a full clause.

A pytest check (`tests/test_writing_style.py`, created in M1) fails if an em dash or a semicolon appears in
Markdown files or notebook Markdown cells outside code. This file is excluded, because it quotes the
characters it bans. Clause-joining colons cannot be detected reliably by a script, so they are left to
the writer and to the M9 review, and are never a reason to fail a task.
