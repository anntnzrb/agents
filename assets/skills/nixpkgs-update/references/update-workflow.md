# Nixpkgs Update Detailed Workflow

## Phase 1: Discover Outdated Packages

Query Repology API for outdated nixpkgs packages:

```
task(
  subagent_type="general",
  description="Query Repology outdated packages",
  prompt="Query Repology API for outdated nixpkgs packages.

Step 1 - Get outdated package names:
curl -s --user-agent 'nixpkgs-update/1.0' \
  'https://repology.org/api/v1/projects/?inrepo=nix_unstable&outdated=1&count=100' | \
  jq -r 'keys[:50][]'

Step 2 - For each package, get version details (respect 1 req/sec rate limit):
curl -s --user-agent 'nixpkgs-update/1.0' \
  'https://repology.org/api/v1/project/<name>' | \
  jq '{name: .[0].visiblename, nixpkgs: ([.[] | select(.repo=="nix_unstable")][0].version), newest: ([.[] | select(.status=="newest")][0].version)}'

Return list with: name, nixpkgs_version, newest_version."
)
```

## Phase 2: Filter Candidates (Strict)

From Repology results, apply strict filtering. **Only keep packages that meet ALL criteria:**

### Must Pass ALL:
1. **Location**: `pkgs/by-name/` only (not legacy paths)
2. **Type**: Rust (`buildRustPackage`, `cargoHash`) OR Go (`buildGoModule`, `vendorHash`)
3. **Version bump**: Patch or minor version (reject major bumps like 1.x → 2.x)
4. **Platform**: Must support current platform (see platform check below)

### Check with Glob/Grep:
```bash
# Check if package exists in by-name
ls pkgs/by-name/*/<package>/package.nix

# Check if Rust or Go
grep -l "buildRustPackage\|cargoHash" pkgs/by-name/*/<package>/package.nix
grep -l "buildGoModule\|vendorHash" pkgs/by-name/*/<package>/package.nix
```

### Platform Check (CRITICAL)
```bash
# Get current system
CURRENT_PLATFORM=$(nix eval --raw --impure --expr 'builtins.currentSystem')
# e.g., "aarch64-darwin" or "x86_64-linux"

# Check if package supports current platform
nix eval .#<package>.meta.platforms --json | jq -e 'contains(["'$CURRENT_PLATFORM'"])'
# OR check for platform restrictions in package.nix:
grep -E "platforms\s*=.*linux" pkgs/by-name/*/<package>/package.nix  # Linux-only, skip on macOS
grep -E "platforms\s*=.*darwin" pkgs/by-name/*/<package>/package.nix  # macOS-only, skip on Linux
```

**Discard packages that cannot be built/tested on current platform.**

**Discard any package that doesn't pass ALL filters.**

## Phase 3: Validate Each Candidate

For EACH filtered candidate, spawn Explore agent to verify simplicity:

```
task(
  subagent_type="explore",
  description="Validate package complexity",
  prompt="Thoroughness: quick

Check pkgs/by-name/*/<package>/package.nix for:
  1. has_patches: any patches = [] or patches directory?
  2. has_complex_postinstall: complex substituteInPlace, wrapProgram with many deps?
  3. has_overrides: overrideAttrs, overrideModAttrs?
  4. complexity: simple/medium/complex
  5. platform_restricted: does it have 'platforms = lib.platforms.linux' or similar restriction?

Return JSON: {has_patches: bool, complexity: 'simple'|'medium'|'complex', platform_restricted: bool, platforms: string}
Only packages with has_patches=false AND complexity='simple' AND supports current platform are acceptable."
)
```

**Only packages with `has_patches=false` AND `complexity=simple` AND `supports current platform` proceed to selection.**

## Phase 4: Present Candidates (Multi-Select)

Present ONLY validated easy candidates:

```
Present candidates to user for selection (output directly):

## Select Packages to Update

| # | Package | Version | Type |
|---|---------|---------|------|
| 1 | some-rust-pkg | 1.0.0 → 1.0.1 | Rust, simple |
| 2 | some-go-pkg | 0.5.0 → 0.5.1 | Go, simple |

Ask: "Which packages would you like to update? (enter numbers, e.g., 1,2)"
```

**Never show:**
- "may need manual work"
- "complex"
- "has patches"
- Major version bumps
- **Platform-restricted packages that can't be tested locally**

## Phase 5: Parallel Updates with Git Worktrees

### Why Worktrees?
Multiple agents cannot `git switch` on the same repo simultaneously. Worktrees provide isolated working directories sharing the same git history.

### Setup Worktrees
For each selected package, create isolated worktree:

```bash
# From main repo (stays on master, untouched)
git worktree add /tmp/nixpkgs-<package>-<version> -b <package>-<version> master
```

### Launch Parallel Agents

```
// Single message with N Task calls, each with its own worktree:
task(subagent_type="general", description="Update pkg1", prompt="Update pkg1 in /tmp/nixpkgs-pkg1-v1...")
task(subagent_type="general", description="Update pkg2", prompt="Update pkg2 in /tmp/nixpkgs-pkg2-v2...")
```

### Update Agent Prompt Template

```
Update the nixpkgs package: <PACKAGE>
Current version: <OLD_VERSION>
Target version: <NEW_VERSION>

## Setup
Working directory: /tmp/nixpkgs-<PACKAGE>-<NEW_VERSION>
(Worktree already created, you are on branch <PACKAGE>-<NEW_VERSION>)

## IMPORTANT RULES
- **10 MINUTE TIMEOUT**: If any build step exceeds 10 minutes, ABORT and report failure
- **NEVER SKIP nixpkgs-review**: This step is MANDATORY, not optional
- Use `timeout 600` prefix for long-running commands

## Steps

1. **Verify worktree:**
   cd /tmp/nixpkgs-<PACKAGE>-<NEW_VERSION>
   git status  # Should show branch <PACKAGE>-<NEW_VERSION>

2. **Run nix-update (with timeout):**
   timeout 600 nix run nixpkgs#nix-update -- <PACKAGE>

   If timeout: ABORT, cleanup worktree, report "build timeout"

3. **Build and verify (with timeout):**
   timeout 600 nix build .#<PACKAGE>

   If timeout: ABORT, cleanup worktree, report "build timeout"
   If build fails: ABORT, cleanup worktree, report "build failed"

   ./result/bin/<BINARY> --version

4. **Test dependent packages (MANDATORY - DO NOT SKIP):**
   timeout 600 nix run nixpkgs#nixpkgs-review -- wip --print-result

   If timeout: ABORT, cleanup worktree, report "review timeout"
   This step is NOT optional. Never skip it.

5. **Commit:**
   git add -A
   git commit -m "$(cat <<'EOF'
<PACKAGE>: <OLD_VERSION> -> <NEW_VERSION>

https://github.com/<OWNER>/<REPO>/releases/tag/v<NEW_VERSION>
EOF
)"

6. **Push to fork:**
   git push --set-upstream fork <PACKAGE>-<NEW_VERSION>

7. **Create PR:**
   gh pr create --repo NixOS/nixpkgs \
     --title "<PACKAGE>: <OLD_VERSION> -> <NEW_VERSION>" \
     --body "$(cat <<'EOF'
## Description
Updates `<PACKAGE>` from <OLD_VERSION> to <NEW_VERSION>.

## Testing
- [x] Built locally
- [x] Ran nixpkgs-review wip

## Links
- Release: https://github.com/<OWNER>/<REPO>/releases/tag/v<NEW_VERSION>
EOF
)"

8. **Return:** PR URL or error message

## On Failure
If any step fails or times out:
1. Cleanup: git worktree remove /tmp/nixpkgs-<PACKAGE>-<NEW_VERSION> --force
2. Delete branch: git branch -D <PACKAGE>-<NEW_VERSION>
3. Report failure with reason
```

### Cleanup Worktrees

After all agents complete, cleanup:

```bash
git worktree remove /tmp/nixpkgs-<package>-<version>
# Repeat for each worktree
```

## Phase 6: Collect Results

Task results return automatically when subagents complete. Present summary:

```
## Update Results

| Package      | Version          | Status | PR     |
|--------------|------------------|--------|--------|
| some-rust    | 1.0.0 → 1.0.1    | ✅     | #12345 |
| some-go      | 0.5.0 → 0.5.1    | ⏱️     | timeout |
```

Cleanup worktrees after reporting.
