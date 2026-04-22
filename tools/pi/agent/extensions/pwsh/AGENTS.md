# Pwsh extension

## Purpose
Add a built-in style `pwsh` tool for PowerShell command execution.
Keep behavior aligned with Pi `bash` tool semantics (timeouts, truncation, temp-file spill, streaming updates).

## Files
- `index.ts` — tool registration + local PowerShell execution backend
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Windows first tries `pwsh.exe`, then falls back to `powershell.exe`.
- Non-Windows requires `pwsh` on PATH.
- Uses `-NoProfile -NoLogo -NonInteractive -Command`.
- On Windows, prepends UTF-8 output encoding guard.
- On Windows, enforces tool policy: remove `bash` from active tools and ensure `pwsh` is active.
- Runtime caveat (current implementation): command execution uses `spawnSync` for Windows stability.
  - Output is buffered then emitted, not truly streamed in real time.
  - Mid-flight abort responsiveness is limited compared to async `spawn`.
  - Large-output commands are bounded by process `maxBuffer` before tool-level truncation.
- Future improvement path: restore hardened async `spawn` + stream draining + timeout/tree-kill for real-time updates.

## Navigation
Start at `index.ts`.
