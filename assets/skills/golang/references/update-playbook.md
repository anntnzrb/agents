# Update Playbook

Repeatable process for refreshing this Go skill when new Go releases or tooling changes land.

## When to use

Load this file only when the user asks to update, audit, refresh, or research the Go skill itself.
Do NOT load it for normal Go development tasks.

## Refresh checklist

### 1. Verify the latest stable Go release

- Check `go.dev/doc/` for the latest release notes
- Check `endoflife.date/go` for the support window
- Check `https://go.dev/doc/toolchain` for toolchain directive changes
- Confirm which versions are supported: the two most recent major releases

**Query opens:**

```bash
context7 docs /golang/go "Go release notes latest"
web_search "Go latest stable release 202X"
```

Read: `references/sources.md` — update the "Go Releases & Language" section.

### 2. Prune experimental and deprecated material

- Remove any GOEXPERIMENT-only features from baseline recommendations
- Remove features that moved from experimental to stable in the right version file
- Remove any library that has been archived or superseded
- Check `golangci-lint` version and config format: `golangci-lint linters` for available linters

### 3. Update version-scoped modern docs

- If a new major Go release shipped, create a new `cookbook/modern-1.XX-1.YY.md` or revise the range files
- Follow the pattern in `cookbook/modern-1.24-1.26.md`: feature table, code examples with Problems/Solutions/Tips
- Update `cookbook/modern.md` (the index) with the new version row

### 4. Update `references/guide.md`

- Update the "Stable Modern Go Feature Table"
- Update CLI quick reference for any new commands or flag changes
- Update tooling defaults if the ecosystem consensus shifted
- Update the library routing table if there are new recommended defaults
- Update anti-patterns if there are new idioms to prefer or old ones to avoid

### 5. Update `SKILL.md`

- Update the one-line identity and activation triggers if domains expanded
- Update the required follow-up reads table with any new cookbook files
- Update the Must/Must Not list for new idioms or deprecated patterns

### 6. Update cookbook files

- For each updated topic, revise the relevant cookbook file: Problems/Solutions/Tips format
- If a file grows past ~300 lines, consider splitting it and updating the routing table
- Delete any recipe that is no longer correct or superseded

### 7. Validate

```bash
uv run --script assets/skills/skill-creator/scripts/cli.py quick-validate assets/skills/golang
```

### 8. Update sources ledger

- Update `references/sources.md` `Last checked` date
- Add any new official or primary sources discovered during the refresh
- Remove dead links

## Research starting points

When investigating what changed:

| Question | Source |
|---|---|
| What's new in Go 1.XX? | `https://go.dev/doc/go1.XX` |
| What's the current stable Go? | `https://go.dev/dl/` |
| What version is supported? | `https://endoflife.date/go` |
| What changed in golangci-lint? | `https://github.com/golangci/golangci-lint/releases` |
| What are people using? | `web_search "state of golang 202X"` |
| Real-world usage pattern? | `gh search code "pattern" --language=go` |
| Library API details? | Context7: `context7 docs /owner/repo "query"` |
| Style guide updates? | `https://github.com/uber-go/guide` |
| What's the Go blog saying? | `https://go.dev/blog/` |
| Community pulse? | `web_search "site:reddit.com/r/golang best practices 202X"` |

## File dependency order

When updating, follow this order (earlier files feed later ones):

1. `references/sources.md` — source ledger
2. `references/guide.md` — feature table, CLI ref, layout, tooling, routing
3. `cookbook/modern.md` + version files — language/runtime features
4. Topic cookbooks — domain-specific recipes
5. `SKILL.md` — routing table and triggers (last, since it references everything else)
