# Pi Extensions

## Guidelines
Prefer functional over imperative, and stateless over stateful where practical.
- Favor pure helpers and data-in/data-out flows
- Minimize mutable module state; isolate unavoidable state in small scopes (UI components, caches)
- Keep side effects at the edges (I/O, UI, model calls)

## QA

Full gate for extensions (run from the specific extension dir):
- `bun x biome format --write . --config-path ../biome.json`
- `bun x biome lint . --config-path ../biome.json`
- `bun x --package eslint --package eslint-plugin-jsdoc --package @typescript-eslint/parser eslint . --max-warnings 0 --config ../eslint.config.js --no-error-on-unmatched-pattern`
- Verify guidelines criterion is met

NOTE: Fallback to npm (`npx`) if `bun` is unavailable.
