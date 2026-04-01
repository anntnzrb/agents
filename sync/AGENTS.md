# AGENTS.md

This is the isolated sync application.

- `./package.json`: sync app scripts and dependencies
- `./tsconfig.json`: sync app TypeScript config
- `./bun.lock`: sync app lockfile
- `./src/`: application code
- `./test/`: sync-specific tests
- Keep behavior changes deliberate.
- Public callable wrapper exists at repo root as `bin/sync`.
