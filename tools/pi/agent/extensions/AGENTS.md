# Pi Extensions

Full gate for extensions (run from the specific extension dir):
- `bun x biome format --write .`
- `bun x biome lint .`
- `bun x --package eslint --package eslint-plugin-jsdoc --package @typescript-eslint/parser eslint . --max-warnings 0`

NOTE: Fallback to npm (`npx`) if `bun` is unavailable.
