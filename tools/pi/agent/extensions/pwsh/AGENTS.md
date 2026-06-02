# Pwsh extension

## Purpose

Add built-in-style `pwsh` tool for PowerShell execution.
Align with Pi `bash` semantics: timeouts, truncation, temp-file spill, streaming updates where supported.

## Files

- `index.ts` — tool registration + local PowerShell backend
- `tsconfig.json` — strict TS config

## Notes

- Windows: try `pwsh.exe`, fallback `powershell.exe`.
- Non-Windows: require `pwsh` on PATH.
- Uses `-NoProfile -NoLogo -NonInteractive -Command`.
- Windows: prepends UTF-8 output encoding guard.
- Windows policy: remove `bash` from active tools; ensure `pwsh` active.

## Known Limitation

- Current command execution uses `spawnSync` for Windows stability.
  - Output buffered then emitted; not true realtime streaming.
  - Mid-flight abort less responsive than async `spawn`.
  - Large output bounded by process `maxBuffer` before tool truncation.
- Future work: hardened async `spawn` + stream draining + timeout/tree-kill for realtime updates.

## Stop Rules

- Preserve Pi `bash`-style semantics unless the task explicitly changes PowerShell behavior.
- Do not treat the async-spawn future note as current behavior.

## Navigation

Start at `index.ts`.
