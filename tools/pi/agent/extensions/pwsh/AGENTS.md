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

## Navigation
Start at `index.ts`.
