# Pi Extensions

## Guidelines
Prefer functional over imperative, and stateless over stateful where practical.
- Favor pure helpers and data-in/data-out flows
- Minimize mutable module state; isolate unavoidable state in small scopes (UI components, caches)
- Keep side effects at the edges (I/O, UI, model calls)

## QA

Full gate for extensions (run from the specific extension dir):
- `bun x biome format --write . --config-path ../.config/biome.json`
- `bun x biome lint . --config-path ../.config/biome.json --error-on-warnings`
- Verify guidelines criterion is met
- Keep files between 500-1000 SLOC (excluding comments). Beyond 500L consider modularizing.
- All extensions must include AGENTS.md with description + navigation.

NOTE: Fallback to npm (`npx`) if `bun` is unavailable.
