# Changelog Conventions Reference

## Keep a Changelog Format

This specification adheres to Keep a Changelog 1.1.0 standards.

### Categories

Group all changes strictly within these categories in descending order:

1. `Breaking Changes`: Backward-incompatible API, configuration, or CLI changes requiring user migration.
2. `Added`: New user-facing features, commands, flags, or public APIs.
3. `Changed`: Changes to existing functionality or observable behavior.
4. `Deprecated`: Features or APIs slated for removal in future releases.
5. `Removed`: Features, options, or APIs completely removed in this release.
6. `Fixed`: Bug fixes resolving observable errors or unintended behavior.
7. `Security`: Vulnerability remediation or security hardening.

### Entry Formatting Rules

- Verb Tense: Always start with a capitalized past-tense verb (`Added`, `Fixed`, `Changed`, `Removed`, `Deprecated`, `Implemented`, `Updated`).
- Focus: Describe the observable impact on the end user, consumer, or integrator rather than internal implementation mechanics.
- Brevity: Keep entries concise (1 to 2 lines).
- Punctuation: Do not include trailing periods at the end of single-line bullets.
- Attribution: For external PRs and contributors, append `([#PR](https://github.com/owner/repo/pull/PR) by [@author](https://github.com/author))` at the end of the entry.

### Good vs Bad Examples

#### Good
- `Added --dry-run flag to preview changelog patch operations without disk writes`
- `Fixed race condition when parsing multiple package boundaries concurrently`
- `Changed default timeout from 30s to 60s for slow Git remote connections`
- `Removed deprecated --legacy-parser flag`

#### Bad
- `* cli: Added dry-run flag.` (redundant prefix, trailing period)
- `Refactored internal token streaming loop` (internal only, not user-facing)
- `Fixed bug` (vague, lacks actionable detail)
