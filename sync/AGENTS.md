# AGENTS.md

This is the isolated sync application.

- `./package.json`: sync app scripts and dependencies
- `./tsconfig.json`: sync app TypeScript config
- `./bun.lock`: sync app lockfile
- `./src/`: application code
- `./test/`: sync-specific tests
- Keep behavior changes deliberate.
- Public callable entrypoint is `src/cli.ts`; wrappers/tooling should invoke it with an explicit Bun runner.
- Do not depend on wrapper-local environment variables for sync behavior; wrapper policy is source-controlled in rice.

## Launch wrapper contract

- Home Manager agent wrappers invoke this app directly with pinned Nix Bun.
- Launch-time sync policy belongs in `~/repos/rice/nix/modules/home/cli/llm-agents/agent-wrapper-common.sh`.
- Manual sync uses this app's internal watchdog; wrapper launch sync may use a shorter static timeout and soft-fail before agent exec.

## Validation

Run from repo root:
- `bun ./sync/src/cli.ts`
- `cd ./sync && bun run typecheck`
- `cd ./sync && bun test`
- `cd ./sync && bun run test:integration`
