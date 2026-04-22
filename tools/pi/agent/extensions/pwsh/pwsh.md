# PW.SH.md — Windows Completion Handoff (Pi `pwsh` Extension)

Status: **PENDING WINDOWS VALIDATION**  
Owner: next agent run on native Windows  
Scope: verify extension behavior on **native Windows** (not WSL), finalize release confidence.

---

## 1) Why this file exists

This session implemented a new Pi extension tool named `pwsh` and integrated it with existing extensions.  
All checks so far were run on macOS. We now need a native Windows pass to close the loop.

This file is intentionally self-contained so a fresh agent can complete the remaining work with zero prior context.

---

## 2) Original user request (compressed)

User asked for:

- A PowerShell tool similar to built-in `bash`
- Native Windows behavior (`pwsh` / `powershell.exe`), not WSL-first behavior
- Research-driven implementation inspired by other harnesses (especially OpenAI Codex)
- No destructive testing; use temp paths
- Exhaustive quoting/escaping/piping/chaining validation
- Windows-specific confidence before calling implementation complete

Then user requested deterministic Windows policy:

- On Windows, prefer PowerShell strongly
- Final decision: **remove `bash` from active tools on Windows** and ensure `pwsh` is active
- Keep macOS/Linux behavior unchanged

---

## 3) What was implemented

### 3.1 New extension

Added:

- `tools/pi/agent/extensions/pwsh/index.ts`
- `tools/pi/agent/extensions/pwsh/AGENTS.md`
- `tools/pi/agent/extensions/pwsh/tsconfig.json`
- `tools/pi/agent/extensions/pwsh/validation-suite.ps1`

Core behavior:

- Registers tool `pwsh`
- Reuses Pi-style tool execution via `createBashToolDefinition(...)` with custom operations backend
- Uses `pwsh.exe` first on Windows, then `powershell.exe` fallback
- On non-Windows: resolves `pwsh` from common paths/PATH
- Uses `-NoProfile -NoLogo -NonInteractive -Command`
- Uses UTF-8 output prefix on Windows shells
- Supports timeout/abort/tree-kill behavior
- Keeps same truncation semantics as bash-style tool path

### 3.2 Deterministic Windows policy (important)

In `pwsh/index.ts`, function `enforceWindowsToolPolicy(...)` now:

- If `process.platform === "win32"`:
  - removes `bash` from active tools
  - ensures `pwsh` is active

This enforcement runs:

- immediately at extension load
- on `session_start`
- on `before_agent_start`

### 3.3 Guardrails integration

Updated guardrails to inspect `pwsh` calls too:

- `tools/pi/agent/extensions/guardrails/index.ts`
- `tools/pi/agent/extensions/guardrails/wrappers.ts`
- `tools/pi/agent/extensions/guardrails/guardrails.test.ts`
- `tools/pi/agent/extensions/guardrails/AGENTS.md`

Notable updates:

- recognizes shell wrappers: `pwsh`, `pwsh.exe`, `powershell`, `powershell.exe`
- unwraps nested commands with `-Command` as well as `-c`

### 3.4 Spawn output polish

Updated:

- `tools/pi/agent/extensions/spawn-pi/results.ts`

Now `spawn_pi` task summaries display PowerShell calls as:

- `PS> ...`

---

## 4) What was already validated on macOS

- extension gate (format/lint) passed for touched extension dirs
- guardrails tests passed (`16/16`)
- `pwsh` command execution smoke passed (success/non-zero/timeout)
- non-destructive suite passed on macOS:
  - total 29
  - pass 26
  - fail 0
  - skip 3 (Windows-only tests)
- large-output truncation behavior observed and working

---

## 5) Known issues encountered during implementation

1. A quoting test in an ad-hoc JS harness initially failed due to JS string escaping, not tool logic.  
   Fixed by using cleaner test scripts and direct suite execution.

2. One temporary lint install run hit a Bun linking hiccup (`sshpk EEXIST`) in one run.  
   Re-run succeeded.

No known functional bug remains from mac-side validation.

---

## 6) Remaining risk (why Windows test still required)

Even with cross-platform code paths, these must be proven on native Windows:

- actual `process.platform === "win32"` policy behavior under real Pi runtime
- `pwsh.exe` vs `powershell.exe` fallback behavior on real host setups
- Windows commandline quirks (quoting, escaping, path/backslash semantics)
- tool availability/selection in actual session UX after `/reload`

---

## 7) Windows execution playbook (do this exactly)

> Run from repo root: `~/.config/agents` equivalent on Windows clone.

### Step A — Preflight

1. Ensure native Windows shell session (PowerShell), **not WSL**.
2. Confirm tools present:

```powershell
pwsh -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
where.exe pwsh
where.exe powershell
```

3. Confirm repo clean enough to run tests.

```powershell
git status --short
```

### Step B — Full extension gate

Run from each extension dir touched (pwsh, guardrails, spawn-pi):

```powershell
cd tools/pi/agent/extensions/pwsh
bun x biome format --write . --config-path ../.config/biome.json
bun x biome lint . --config-path ../.config/biome.json --error-on-warnings

cd ../guardrails
bun x biome format --write . --config-path ../.config/biome.json
bun x biome lint . --config-path ../.config/biome.json --error-on-warnings
bun test guardrails.test.ts

cd ../spawn-pi
bun x biome format --write . --config-path ../.config/biome.json
bun x biome lint . --config-path ../.config/biome.json --error-on-warnings
```

If Bun unavailable, use fallback per policy (`npx ...`).

### Step C — Sync to live Pi home

```powershell
cd <repo-root>
./bin/sync
```

### Step D — Reload Pi runtime

Inside Pi interactive session, run:

```text
/reload
```

### Step E — Validate deterministic Windows policy

Goal: prove `bash` is removed and `pwsh` is active.

Use this runtime probe script:

```powershell
@'
import ext from "./tools/pi/agent/extensions/pwsh/index.ts";
const calls = [];
const handlers = new Map();
const pi = {
  registerTool() {},
  on(name, fn) { handlers.set(name, fn); },
  getActiveTools() { return ["read", "bash", "edit", "write"]; },
  setActiveTools(next) { calls.push(next); }
};
ext(pi);
if (handlers.has("session_start")) await handlers.get("session_start")();
if (handlers.has("before_agent_start")) await handlers.get("before_agent_start")();
console.log(JSON.stringify(calls, null, 2));
'@ | Set-Content -LiteralPath $env:TEMP\pwsh-policy-probe.mjs -Encoding utf8

bun $env:TEMP\pwsh-policy-probe.mjs
```

Expected: at least one call containing exactly/at least:

- `read`, `edit`, `write`, `pwsh`
- **no `bash`**

### Step F — Run exhaustive non-destructive suite

Run source copy and synced copy both:

```powershell
pwsh -NoProfile -File .\tools\pi\agent\extensions\pwsh\validation-suite.ps1
pwsh -NoProfile -File "$HOME\.pi\agent\extensions\pwsh\validation-suite.ps1"
```

Expected on Windows:

- `fail = 0`
- Windows tests should be `PASS` (not `SKIP`)

### Step G — Real tool-level calls through Pi

From Pi (or harness API), force actual tool exercise with safe temp paths:

1. Short command
2. Medium piped command
3. Long output command (trigger truncation)
4. Timeout command
5. Non-zero exit command
6. Quoting stress command
7. File create/append/read/move in `%TEMP%` only

Minimum examples:

```powershell
$PSVersionTable.PSVersion.ToString()
1..100 | Measure-Object -Sum | Select-Object -ExpandProperty Sum
1..2600 | % { "line $_" }
Start-Sleep -Seconds 3
exit 7
$name='neo'; "hello $name"; 'literal $HOME and `backtick` and "double"'
```

### Step H — Check fallback path (`powershell.exe`)

If possible, test a machine/profile without `pwsh.exe` on PATH (or simulate restricted path) so extension uses `powershell.exe` fallback.

Need to verify:

- tool still executes
- UTF-8 output still acceptable
- timeout behavior still works

---

## 8) Non-destructive test constraints

Required constraints:

- write only under `%TEMP%`/`[IO.Path]::GetTempPath()`
- no registry writes
- no service manipulation
- no privileged operations
- no persistent filesystem changes outside temp

Suite already follows this model.

---

## 9) New tests to add (Windows agent should add if missing)

If all Windows checks pass, still add regression tests where reasonable:

1. **Policy behavior test** (extension-level):
   - when platform win32 + active has bash, ensure setActiveTools excludes bash includes pwsh
2. **No-op policy test**:
   - if active already includes pwsh and no bash, no unnecessary setActiveTools call
3. **Fallback resolution test** (mocked):
   - pwsh missing + powershell present => powershell config chosen
4. **Windows quoting smoke** in suite if any uncovered edge appears

If these tests are hard to add in current infra, document why + add a script-based assertion under `tools/pi/agent/extensions/pwsh/`.

---

## 10) Reporting format for final Windows run

Produce a report with these sections:

1. Host info (Windows version, pwsh version, bun version)
2. Gate outputs (format/lint/test)
3. Sync/reload confirmation
4. Policy proof (`bash` removed, `pwsh` active)
5. Validation suite JSON summary
6. Tool-level live execution evidence
7. Any failures and exact repro commands
8. Fixes applied + files changed
9. Final verdict: `READY` or `NOT READY`

---

## 11) Completion criteria (definition of done)

Mark complete only if all are true:

- [ ] Extension full gate passes on Windows
- [ ] Sync + reload completed
- [ ] Windows policy proven active (`bash` removed, `pwsh` active)
- [ ] Validation suite on Windows has `fail=0`
- [ ] Real Pi tool calls pass for short/medium/long/timeout/non-zero/quoting/piping/file-temp tests
- [ ] Any discovered bug fixed and re-validated
- [ ] Added/updated tests for policy behavior (or documented equivalent guard)

When all checked: this feature can be considered production-ready for native Windows Pi use.

---

## 12) Quick command block (copy/paste)

```powershell
# from repo root
cd tools/pi/agent/extensions/pwsh
bun x biome format --write . --config-path ../.config/biome.json
bun x biome lint . --config-path ../.config/biome.json --error-on-warnings

cd ../guardrails
bun x biome format --write . --config-path ../.config/biome.json
bun x biome lint . --config-path ../.config/biome.json --error-on-warnings
bun test guardrails.test.ts

cd ../spawn-pi
bun x biome format --write . --config-path ../.config/biome.json
bun x biome lint . --config-path ../.config/biome.json --error-on-warnings

cd <repo-root>
./bin/sync

pwsh -NoProfile -File .\tools\pi\agent\extensions\pwsh\validation-suite.ps1
pwsh -NoProfile -File "$HOME\.pi\agent\extensions\pwsh\validation-suite.ps1"
```

---

## 13) Self-contained guarantee

This file is intentionally complete and must be treated as the single source of context for the Windows-side run.
No external session/chat file access is required.

---

Temporary tracked handoff file. Delete after Windows validation closes.
