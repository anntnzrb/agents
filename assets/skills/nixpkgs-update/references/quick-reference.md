# Nixpkgs Update Quick Reference

## Platform Detection

```bash
# Get current system
nix eval --raw --impure --expr 'builtins.currentSystem'
# Returns: aarch64-darwin, x86_64-linux, aarch64-linux, x86_64-darwin

# Check package platforms
nix eval .#<pkg>.meta.platforms --json

# Common platform patterns in package.nix:
# lib.platforms.linux     → Linux only (skip on macOS)
# lib.platforms.darwin    → macOS only (skip on Linux)
# lib.platforms.unix      → Both Linux and macOS (OK)
# lib.platforms.all       → All platforms (OK)
```

## Git Worktrees

```bash
# Create worktree with new branch
git worktree add /tmp/nixpkgs-<pkg>-<ver> -b <pkg>-<ver> master

# List worktrees
git worktree list

# Remove worktree
git worktree remove /tmp/nixpkgs-<pkg>-<ver>

# Force remove (if dirty)
git worktree remove /tmp/nixpkgs-<pkg>-<ver> --force

# Prune stale worktrees
git worktree prune
```

## Timeout Commands

```bash
# 10 minute timeout for builds
timeout 600 nix build .#<pkg>

# Check exit code: 124 = timeout
if [ $? -eq 124 ]; then echo "TIMEOUT"; fi
```

## Repology API

```bash
# Get outdated nixpkgs packages (User-Agent required!)
curl -s --user-agent "nixpkgs-update/1.0" \
  "https://repology.org/api/v1/projects/?inrepo=nix_unstable&outdated=1&count=50" | \
  jq -r 'keys[:20][]'

# Check specific package versions
curl -s --user-agent "nixpkgs-update/1.0" \
  "https://repology.org/api/v1/project/<name>" | \
  jq '{nixpkgs: ([.[] | select(.repo=="nix_unstable")][0].version), newest: ([.[] | select(.status=="newest")][0].version)}'
```

## Nix Commands

```bash
# Update package (auto-updates hashes)
timeout 600 nix run nixpkgs#nix-update -- <pkg>

# Build package
timeout 600 nix build .#<pkg>

# Test dependent packages (MANDATORY)
timeout 600 nix run nixpkgs#nixpkgs-review -- wip --print-result
```

## Commit Format

```
<pkg>: <old-version> -> <new-version>
```

## Candidate Criteria Summary

| Criteria     | Required Value                  |
| ------------ | ------------------------------- |
| Location     | `pkgs/by-name/`                 |
| Type         | Rust OR Go                      |
| has_patches  | `false`                         |
| complexity   | `simple`                        |
| Version bump | patch/minor only                |
| **Platform** | **Must support current system** |

**If ANY criterion fails, discard the candidate. Never present options that can't be tested locally.**

## Failure Handling

| Failure               | Action                   |
| --------------------- | ------------------------ |
| Build timeout (>10m)  | Discard, cleanup, report |
| Build error           | Discard, cleanup, report |
| Review timeout (>10m) | Discard, cleanup, report |
| Platform mismatch     | Never present to user    |
