# Development

The sync application is an isolated Bun and TypeScript project under `sync/`.

## Run from source

From the repository root:

```bash
bun ./sync/src/cli.ts
```

## Run checks

```bash
cd sync
bun run check
bun run typecheck
bun test
bun run test:integration
```

Run focused tests while developing:

```bash
cd sync
bun test ./test/managed-tools.test.ts
bun test ./test/wrappers.test.ts
```

## Project structure

```text
sync/
  src/core/       reconciliation plans, launchers, wrappers, managed tools
  src/extensions/ extension dependency hooks
  src/packages/   package source and bootstrap logic
  src/runtime/    filesystem, lock, process, and error boundaries
  test/           unit and process-level integration tests
```

## Change contracts

- Keep `sync/src/cli.ts` as the public entrypoint.
- Use an explicit Bun runner in commands and wrappers.
- Keep generated wrapper behavior inside the sync application.
- Validate external files and network data at their boundary.
- Make filesystem operations idempotent and safe to retry.
- Add integration coverage when a change creates a new generated target.
