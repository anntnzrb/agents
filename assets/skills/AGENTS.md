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

## Hard bans

- No Bash/sh/PowerShell wrappers as bundled skill entrypoints.
- No `*.sh` files in skills.
- No `source`, `./script`, shebang, or executable-bit assumptions in public docs.
- No raw `python`, `python3`, `pip`, or `pip install` in public run paths.
- No `pyproject.toml` or `uv.lock` per skill unless the user explicitly asks for package semantics.
- No POSIX-only paths like `/tmp`; use `<temp-dir>` in docs and `tempfile` in code.

## Cross-platform code rules

- Use `pathlib.Path`, `tempfile`, and explicit encodings.
- Use `subprocess.run([...], shell=False)` and preserve child exit codes.
- Print human errors to stderr.
- Return `2` for usage/config/platform errors.
- Return `127` for missing required external executables.
- Platform-specific skills must fail clearly on unsupported OS instead of relying on shell failure.

## Validation

Run against the skill-screator skill.

Before handoff after skill executable changes:

```text
uv run --script <skill-dir>/scripts/cli.py --help
git diff --check
```

For migrated library code, run the smallest relevant pytest/ruff/pyright gate with explicit `uv run --with ...` deps.
