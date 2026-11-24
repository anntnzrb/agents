---
name: code-metrics
description: "Use when scoring code with CRAP metrics, mutation testing, or structural duplicate detection, not for linting."
license: AGPL-3.0-or-later
compatibility: Requires uv. The first run of each pinned tool needs network access to GitHub.
---

# Code metrics

Run three deterministic quality tools by Robert C. Martin on Python, TypeScript, Rust, Go, Java, or Clojure code:

| Tool | Measures | Act on |
| --- | --- | --- |
| `crapper` | CRAP per function: `CC² × (1 − coverage)³ + CC` | Functions above 10: split them, test them, or both |
| `mutator` | Mutants the tests fail to kill | Survivors: add an assertion that kills each one, or delete the dead code |
| `dryer` | Structural duplicate pairs, Jaccard score | Pairs at 0.82 or above: review, then merge real duplication |

These are on-demand checks. NEVER add them to CI or a pre-commit hook unless the user asks.

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py <tool> <tool-args>...
```

Set `<skill-dir>` to this skill directory. The wrapper runs `uvx --from git+https://github.com/unclebob/<tool>@<sha>` at the commits pinned in `scripts/cli.py`, gives `mutator` the pinned `crapper`, and preserves the exit code. NEVER clone the tools or run their `./crapper`-style launchers. Those launchers build a `.venv` with pip next to the checkout. Examples below use `code-metrics <tool>` as shorthand. Run `code-metrics <tool> --help` for every option.

## Before a run

- Run from the project root on a committed tree. `mutator` rewrites source files while it tests each mutant, then restores them. Check `git status` after the run.
- The tools write `.metrics/` and, with coverage, `target/coverage/` and `.coverage` in the project root. Delete them at the end unless the project ignores them.
- Start with one file or `--changed`. A first `mutator` run over a tree executes every covered mutant.

## Python coverage

Without `--coverage-command` or `--no-coverage`, `crapper` and `mutator` run coverage with `.venv/bin/python` or `python3` and pip-install `coverage` and `pytest` into that interpreter when missing. NEVER let them install into a user or system interpreter. Pass a uv command that writes LCOV where the tools read it:

```text
code-metrics crapper --coverage-command "uv run --no-project --with pytest,coverage -- sh -c 'coverage run --source=<src> -m pytest -q <tests> && coverage lcov -o target/coverage/python/lcov.info'" <src>
```

Add the project's test dependencies to `--with`, or use `uv run` inside a uv project instead of `--no-project`. Coverage counts only code that runs in the test process. When tests drive the code as a subprocess, every function reads 0% or uncovered: use `crapper --no-coverage` for complexity and `mutator --no-coverage --test-command "<cmd>"` so every site runs.

## Common calls

```text
code-metrics crapper --no-coverage <path>             # complexity only
code-metrics crapper --threshold 30 <path>            # exit 2 when the worst score is higher; needs coverage
code-metrics mutator --scan <file>                    # list mutation sites, run nothing
code-metrics mutator --test-command "<cmd>" <file>    # run mutants against this test command
code-metrics mutator --lines 12,40 <file>             # only these source lines
code-metrics dryer <path>                             # duplicate candidates, closest first
```

`mutator` exits 3 when any mutant survives. Once `.metrics/mutate` exists, the next run reruns only survivors and changed functions.

## Report

Name the tool, the scope, and the commit. Quote the worst rows from the table, not the whole report. For each survivor or score you act on, name the file and line and the change it drove. A metric is evidence for a decision. NEVER raise a score with tests that assert nothing about behavior.

## Maintenance

The pins live in `PINS` in `scripts/cli.py`. No workflow tracks them. To update, read the upstream log since each pin, smoke-test `crapper --no-coverage`, `mutator --scan`, and one `mutator` run on a scratch copy of a project, then replace the full commit hashes.
