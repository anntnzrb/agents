---
disable-model-invocation: true
name: nixpkgs-update
description: "Use when updating a nixpkgs package or contributing a package bump with nix-update or nixpkgs-review."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Nixpkgs Package Update

Batch NixOS/nixpkgs update workflow: Repology discovery; strict easy-update filtering; parallel git worktrees.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Phase prompts, PR templates, failure handling|`references/update-workflow.md`|Before executing or delegating updates|
|Commands, platform checks, candidate tables|`references/quick-reference.md`|Before running update commands|

Exact referenced command syntax MUST survive delegation.

## Workflow

`DISCOVER → FILTER → VALIDATE → SELECT → UPDATE → REPORT`

1. **DISCOVER**: Query Repology API for outdated `nix_unstable` packages with User-Agent `nixpkgs-update/1.0`; collect `name`, `nixpkgs_version`, `newest_version`. Use exact Repology commands from either required reference.
2. **FILTER**: Keep only packages in `pkgs/by-name/` of type Rust | Go, with `has_patches=false`, `complexity=simple`, patch/minor version bumps, and support for the current system. Rust requires `buildRustPackage`/`cargoHash`; Go requires `buildGoModule`/`vendorHash`. Reject major bumps and packages restricted from local testing.
3. **VALIDATE**: Spawn one Explore agent per filtered candidate. Each inspects `pkgs/by-name/*/<package>/package.nix` for patches, complex install logic, overrides, complexity, and platform restrictions. Proceed only when `has_patches=false`, `complexity=simple`, and current-platform support.
4. **SELECT**: Present only validated easy candidates in a multi-select table containing package, version bump, and type. Ask: `Which packages would you like to update? (enter numbers, e.g., 1,2)`.
5. **UPDATE**: Work only from the nixpkgs checkout the user intends to contribute from. Create one worktree per selected package:

```bash
git worktree add <temp-dir>/nixpkgs-<package>-<version> -b <package>-<version> master
```

Launch one agent per worktree; agents MUST not `git switch` in one shared repo. Each agent MUST:

1. Verify worktree and branch.
2. Run `timeout 600 nix run nixpkgs#nix-update -- <PACKAGE>`.
3. Run `timeout 600 nix build .#<PACKAGE>`.
4. Run a binary version check when applicable.
5. Run `timeout 600 nix run nixpkgs#nixpkgs-review -- wip --print-result` (`nixpkgs-review` mandatory; NEVER skip).
6. Commit with title `<PACKAGE>: <OLD_VERSION> -> <NEW_VERSION>`.
7. Push to fork and create a PR against `NixOS/nixpkgs`.
8. Return PR URL or failure reason.

Every long build/review command MUST use `timeout 600`. Use the full agent prompt, commit body, PR body, and cleanup commands from `references/update-workflow.md`.
6. **REPORT**: Collect and display PR URLs/results:

```
## Update Results

| Package      | Version          | Status | PR     |
|--------------|------------------|--------|--------|
| some-rust    | 1.0.0 → 1.0.1    | ✅     | #12345 |
| some-go      | 0.5.0 → 0.5.1    | ⏱️     | timeout |
```

Clean up successful worktrees after reporting. Failed worktrees MUST already be removed by failure handling.

## Non-negotiables and failure handling

- Present only candidates passing every strict filter; NEVER show packages needing manual work, complex packages, packages with patches, major bumps, or packages untestable on the current platform. Platform support is mandatory.
- On failure or timeout, abort that package, clean up its worktree/branch, and report the reason.
- Build timeout (>10m), build error, or review timeout (>10m) → discard, clean up, report.
- Platform mismatch → NEVER present to user.
- Cleanup commands are in `references/update-workflow.md` and `references/quick-reference.md`.
