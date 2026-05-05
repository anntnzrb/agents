# AGENTS.md

This is the isolated sync application.

## Scope

- `./package.json`: sync app scripts and dependencies
- `./tsconfig.json`: sync app TypeScript config
- `./bun.lock`: sync app lockfile
- `./src/`: application code
- `./test/`: sync-specific tests

## Contracts

- Keep behavior changes deliberate.
- Public callable entrypoint is `src/cli.ts`; wrappers/tooling invoke it with an explicit Bun runner.
- Sync behavior must not depend on wrapper-local environment variables; wrapper policy is source-controlled in rice.

## Launch Wrapper Contract

- Home Manager agent wrappers invoke this app directly with pinned Nix Bun.
- Launch-time sync policy belongs in `~/repos/rice/nix/modules/home/cli/llm-agents/agent-wrapper-common.sh`.
- Manual sync uses this app's internal watchdog; wrapper launch sync may use a shorter static timeout and soft-fail before agent exec.

## Validation

Run from repo root when sync code or tests change:
- `bun ./sync/src/cli.ts`
- `cd ./sync && bun run typecheck`
- `cd ./sync && bun test`
- `cd ./sync && bun run test:integration`

## Stop Rules

- For docs-only edits, skip sync execution unless invocation behavior changed.
- Do not change launch-wrapper behavior here; update rice when wrapper policy changes.
