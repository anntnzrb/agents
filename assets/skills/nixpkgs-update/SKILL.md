---
name: nixpkgs-update
description: Update nixpkgs packages with nix-update/nixpkgs-review or contribute package bumps upstream.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Nixpkgs Package Update

Batch workflow for contributing package updates to NixOS/nixpkgs. Uses Repology API for discovery, strict filtering for easy updates, and git worktrees for parallel execution.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Phase prompts, PR templates, failure handling | `references/update-workflow.md` | Before executing or delegating updates |
| Commands, platform checks, candidate tables | `references/quick-reference.md` | Before running update commands |

Exact referenced command syntax MUST survive delegation.

## Workflow

```
1. DISCOVER  → Query Repology API
2. FILTER    → Keep only Rust/Go + by-name + no patches + buildable platform
3. VALIDATE  → Parallel Explore agents confirm "simple" complexity
4. SELECT    → Present candidates to user (multi-select)
5. UPDATE    → Parallel agents with git worktrees (10m timeout)
6. REPORT    → Collect and display PR URLs
```

## Non-negotiables

- Work only from the nixpkgs checkout the user intends to contribute from.
- Only present candidates that pass every strict filter.
- Never show packages that may need manual work, are complex, have patches, are major version bumps, or cannot be tested on the current platform.
- Platform support is mandatory: discard packages that cannot be built/tested locally.
- Use git worktrees for parallel updates; multiple agents must not `git switch` in one repo.
- Every long build/review command must use `timeout 600`.
- `nixpkgs-review` is mandatory; never skip it.
- On failure or timeout, abort that package, clean up its worktree/branch, and report the reason.

## Phase summary

### 1. Discover outdated packages

Query Repology for outdated `nix_unstable` packages using User-Agent `nixpkgs-update/1.0`. Collect `name`, `nixpkgs_version`, and `newest_version`. Use the exact Repology commands in `references/update-workflow.md` or `references/quick-reference.md`.

### 2. Filter candidates strictly

Keep only packages meeting all criteria:

| Criteria     | Required Value              |
| ------------ | --------------------------- |
| Location     | `pkgs/by-name/`             |
| Type         | Rust OR Go                  |
| has_patches  | `false`                     |
| complexity   | `simple`                    |
| Version bump | patch/minor only            |
| Platform     | Must support current system |

Rust packages must use `buildRustPackage`/`cargoHash`; Go packages must use `buildGoModule`/`vendorHash`. Reject major bumps and platform-restricted packages that cannot be tested locally.

### 3. Validate each candidate

Spawn Explore agents for each filtered candidate. They must inspect `pkgs/by-name/*/<package>/package.nix` for patches, complex install logic, overrides, complexity, and platform restrictions. Only `has_patches=false`, `complexity=simple`, and current-platform support proceed.

### 4. Present candidates

Present only validated easy candidates as a multi-select table with package, version bump, and type. Ask: `Which packages would you like to update? (enter numbers, e.g., 1,2)`.

### 5. Update in parallel worktrees

Create one worktree per selected package:

```bash
git worktree add <temp-dir>/nixpkgs-<package>-<version> -b <package>-<version> master
```

Launch one update agent per worktree. Each agent must:

1. Verify worktree and branch.
2. Run `timeout 600 nix run nixpkgs#nix-update -- <PACKAGE>`.
3. Run `timeout 600 nix build .#<PACKAGE>`.
4. Run a binary version check when applicable.
5. Run `timeout 600 nix run nixpkgs#nixpkgs-review -- wip --print-result`.
6. Commit with title `<PACKAGE>: <OLD_VERSION> -> <NEW_VERSION>`.
7. Push to fork and create a PR against `NixOS/nixpkgs`.
8. Return PR URL or failure reason.

Use the full agent prompt, commit body, PR body, and cleanup commands from `references/update-workflow.md`.

### 6. Report and clean up

Collect task results and display:

```
## Update Results

| Package      | Version          | Status | PR     |
|--------------|------------------|--------|--------|
| some-rust    | 1.0.0 → 1.0.1    | ✅     | #12345 |
| some-go      | 0.5.0 → 0.5.1    | ⏱️     | timeout |
```

Clean up successful worktrees after reporting. Failed worktrees must already be removed by failure handling.

## Failure handling

| Failure               | Action                   |
| --------------------- | ------------------------ |
| Build timeout (>10m)  | Discard, cleanup, report |
| Build error           | Discard, cleanup, report |
| Review timeout (>10m) | Discard, cleanup, report |
| Platform mismatch     | Never present to user    |

Cleanup commands are in `references/update-workflow.md` and `references/quick-reference.md`.
