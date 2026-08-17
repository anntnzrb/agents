# Manage shared skills

Use `skills/current/` for skills that sync publishes to enabled harnesses. Use `skills/legacy/` for archived skills.

## Change a skill

1. Read the [skills gate](../assets/skills-gate.md).
2. Edit `skills/current/<name>/`.
3. Run the skill's focused tests.
4. Run the validation that matches the changed files.
5. Run `bun ./sync/src/cli.ts` from the repository root.
6. Inspect the generated skill in one harness home.

Keep development credentials in an ignored `.env` file. Commit an `.env.example` with placeholder names when users need to know the variables.

## Validate Python files

For a skill with Python code, run the formatting and lint checks:

```bash
uvx ruff format skills/current/<name>
uvx ruff check --select ALL --ignore COM812,D203,D213 skills/current/<name>
```

Run the smallest relevant test and type-check commands listed by the skill.

## Validate an executable skill

Executable skills use `scripts/cli.py` as their public entrypoint. Check the command after changing executable behavior:

```bash
uv run --script skills/current/<name>/scripts/cli.py --help
git diff --check
```

Do not add a shell wrapper. Put runtime dependencies in the PEP 723 metadata inside `scripts/cli.py`.

## Validate skill metadata

After changing `SKILL.md` frontmatter or package structure, run the repository validator:

```bash
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/<name>
git diff --check
```

Keep the `description` field to one trigger-focused sentence of at most 120 characters.

## Archive a skill

Move the complete directory into `skills/legacy/`:

```bash
mv skills/current/<name> skills/legacy/<name>
bun ./sync/src/cli.ts
```

The next sync removes the managed copy from harness homes. Sync does not publish anything under `skills/legacy/`.
