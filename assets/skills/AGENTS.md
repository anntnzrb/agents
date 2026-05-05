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
