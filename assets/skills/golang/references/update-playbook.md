# Go skill update playbook

Purpose: repeatably refresh this Go skill after new Go releases or tooling changes.

Use only when the user asks to update, audit, refresh, or research the Go skill itself; NEVER load for normal Go development.

## Refresh checklist

1. **Latest stable Go**
   - Check `go.dev/doc/` for latest release notes.
   - Check `endoflife.date/go` for the support window.
   - Check `https://go.dev/doc/toolchain` for toolchain-directive changes.
   - Confirm support for the two most recent major releases.

   **Query opens:**

   ```bash
   context7 docs /golang/go "Go release notes latest"
   web_search "Go latest stable release 202X"
   ```

   Read `references/sources.md`; update its `Go Releases & Language` section.

2. **Prune experimental/deprecated material**
   - Remove GOEXPERIMENT-only features from baseline recommendations.
   - Remove features moved from experimental to stable in the appropriate version file.
   - Remove archived or superseded libraries.
   - Check `golangci-lint` version/config format with `golangci-lint linters` for available linters.

3. **Version-scoped modern docs**
   - If a new major Go release shipped, create `cookbook/modern-1.XX-1.YY.md` or revise range files.
   - Follow `cookbook/modern-1.24-1.26.md`: feature table plus code examples with Problems/Solutions/Tips.
   - Add the new version row to `cookbook/modern.md`.

4. **`references/guide.md`**
   Update:
   - Stable Modern Go Feature Table.
   - CLI quick reference for new commands/flag changes.
   - Tooling defaults if ecosystem consensus shifted.
   - Library routing table for new recommended defaults.
   - Anti-patterns for new preferred idioms or obsolete ones.

5. **`SKILL.md`**
   Update:
   - One-line identity and activation triggers if domains expanded.
   - Required follow-up reads table with new cookbook files.
   - Must/Must Not list for new idioms or deprecated patterns.

6. **Cookbooks**
   - Revise each updated topic's cookbook using Problems/Solutions/Tips.
   - If a file grows past ~300 lines, consider splitting it and updating the routing table.
   - Delete recipes no longer correct or superseded.

7. **Validate**

   ```bash
   uv run --script assets/skills/skill-creator/scripts/cli.py quick-validate assets/skills/golang
   ```

8. **Sources ledger**
   - Update `references/sources.md` `Last checked` date.
   - Add new official or primary sources discovered during refresh.
   - Remove dead links.

## Research starting points

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

Update in this order; earlier files feed later ones:

1. `references/sources.md` — source ledger.
2. `references/guide.md` — feature table, CLI reference, layout, tooling, routing.
3. `cookbook/modern.md` + version files — language/runtime features.
4. Topic cookbooks — domain-specific recipes.
5. `SKILL.md` — routing table and triggers; last because it references everything else.
