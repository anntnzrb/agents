# AGENTS.md

## Executable skills

- Public entrypoint: `scripts/cli.py`.
- Public invocation:
  ```text
  uv run --script <skill-dir>/scripts/cli.py ...
  ```
- Put runtime deps in PEP 723 metadata inside `scripts/cli.py`.
- Put reusable code in `lib/<module>/`; make `scripts/cli.py` add `lib/` to `sys.path`.
- Keep `SKILL.md` focused on when/how to use the skill; move bulk docs to `references/`.
- Progressive disclosure standard:
  - `SKILL.md` is the entrypoint/router only: triggers, activation criteria, minimal workflow, tool/script routing, and follow-up reads.
  - Target `SKILL.md` at ≤150 lines; hard cap 250 lines unless the skill has no bundled references.
  - Move stable explanation/API notes to `references/`; move worked examples to `cookbook/`; move deterministic fetching/parsing/scoring/generation into `scripts/`.
  - When bundled docs exist, `SKILL.md` MUST include a required follow-up reads table with columns: `Need`, `Read`, `When`.
  - Reference files over 300 lines MUST start with a table of contents or equivalent section index.
  - Do not place large always-loaded docs in skill-package `AGENTS.md`; use `references/` and route to them from `SKILL.md`.

## Portability Constraints

- Bundled skill entrypoints use `scripts/cli.py`, not Bash/sh/PowerShell wrappers.
- Skills do not include `*.sh` files.
- Public docs avoid `source`, `./script`, shebang, or executable-bit assumptions.
- Public run paths use `uv run --script`, not raw `python`, `python3`, `pip`, or `pip install`.
- Per-skill `pyproject.toml` or `uv.lock` belongs only in package-style skills when the user explicitly asks for package semantics.
- Docs use `<temp-dir>` and code uses `tempfile`; avoid POSIX-only paths like `/tmp`.

## Cross-platform code rules

- Use `pathlib.Path`, `tempfile`, and explicit encodings.
- Use `subprocess.run([...], shell=False)` and preserve child exit codes.
- Print human errors to stderr.
- Return `2` for usage/config/platform errors.
- Return `127` for missing required external executables.
- Platform-specific skills must fail clearly on unsupported OS instead of relying on shell failure.

## Full Gate

```
uvx ruff format <path> # fmt
uvx ruff check --select ALL <path> # aggressive lint (try to fix most)
```

## Validation

Use the `skill-creator` skill for skill creation, audits, packaging, or trigger/structure work.

Before handoff after skill executable changes:

```text
uv run --script <skill-dir>/scripts/cli.py --help
git diff --check
```

For migrated library code, run the smallest relevant pytest/ruff/pyright gate with explicit `uv run --with ...` deps.

## Stop Rules

- Skip executable validation for docs-only edits unless the docs change public invocation behavior.
- Do not add package metadata, shell wrappers, or platform assumptions unless the user explicitly requests that scope.
