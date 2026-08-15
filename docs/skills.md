# Skills

`skills/current/` is the source of truth for shared skills. Sync publishes this directory to every enabled harness.

`skills/legacy/` stores archived skills. Sync never publishes it.

## Change a skill

1. Read `assets/skills-gate.md`.
2. Edit the skill under `skills/current/<name>/`.
3. Run the skill's focused tests.
4. Run `bun ./sync/src/cli.ts`.
5. Verify the generated skill in one harness home.

A skill directory normally contains `SKILL.md` and may contain scripts, references, tests, and environment examples. Keep credentials in ignored `.env` files. Commit `.env.example` when users need a schema.

## Archive a skill

Move the complete skill directory from `skills/current/` to `skills/legacy/`. The next sync removes the managed copy from harness homes.
