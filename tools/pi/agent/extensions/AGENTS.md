# Pi Extensions

## Guidelines
Prefer functional over imperative, and stateless over stateful where practical.
- Favor pure helpers and data-in/data-out flows
- Minimize mutable module state; isolate unavoidable state in small scopes (UI components, caches)
- Keep side effects at the edges (I/O, UI, model calls)

## Skills for extension work

- Load `/skill:typescript` for TypeScript extension changes and validation.
- Load `/skill:effect` when touching Effect-based code or when validating Effect patterns.
- If neither applies, skip them.

## QA

Full gate for extensions (run from the specific extension dir):
- `bun x biome format --write . --config-path ../.config/biome.json`
- `bun x biome lint . --config-path ../.config/biome.json --error-on-warnings`
- Verify guidelines criterion is met
- Keep files between 500-1000 SLOC (excluding comments). Beyond 500L consider modularizing
- All extensions must include AGENTS.md with description + navigation

NOTE: Fallback to npm (`npx`) if `bun` is unavailable.

## Native Pi tool override philosophy

When modifying or overriding built-in Pi tools (`read`, `write`, `edit`, `grep`, `find`, etc.), use a conservative approach:
- Prefer thin wrappers and UI-only overrides over reimplementing tool execution.
- Minimize behavioral drift from native defaults unless explicitly required.
- Keep change-surface small, reversible, and easy to diff.
- Treat this as guidance, not a hard cap; break it only with clear justification.
