# Manage shared skills

Use `skills/current/` for skills that sync publishes to every enabled harness. Use `skills/legacy/` for archived skills.

## Change a skill

1. Read `assets/skills-gate.md`.
2. Edit `skills/current/<name>/`.
3. Run the skill's focused tests.
4. Run the validation that matches the changed files.
5. Run `bun ./sync/src/cli.ts` from the repository root.
6. Inspect the generated skill in one harness home.

Keep credentials in an ignored `.env` file. If users need the variable names, commit an `.env.example` with placeholder values.

## Validate Python files

For a skill with Python code, run the full formatting and lint gate:

```bash
uvx ruff format skills/current/<name>
uvx ruff check --select ALL --ignore COM812,D203,D213 skills/current/<name>
```

Run the smallest relevant test and type-check commands listed by the skill.

## Validate an executable skill

Executable skills use `scripts/cli.py` as their public entrypoint. Check the public command after changing executable behavior:

```bash
uv run --script skills/current/<name>/scripts/cli.py --help
git diff --check
```

Do not add a shell wrapper. Put runtime dependencies in the PEP 723 metadata inside `scripts/cli.py`.

## Validate skill metadata

After changing `SKILL.md` frontmatter or package structure, use the repository skill validator:

```bash
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/<name>
git diff --check
```

The `description` field must remain one trigger-focused sentence of at most 120 characters.

## Archive a skill

Move the complete directory into `skills/legacy/`:

```bash
mv skills/current/<name> skills/legacy/<name>
bun ./sync/src/cli.ts
```

The next sync removes the managed copies from harness homes. Sync does not publish anything under `skills/legacy/`.
