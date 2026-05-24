---
description: Windows shell policy for the OMP bash tool
alwaysApply: true
---

On Windows, OMP's `bash` tool is Git Bash/MSYS-style Bash, not PowerShell.

When the task is Windows-native shell work:
- Call `pwsh.exe` explicitly from `bash` instead of typing PowerShell cmdlets directly into Bash.
- Prefer: `pwsh.exe -NoProfile -NoLogo -NonInteractive -Command '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; <script>'`
- For multiline or quote-heavy commands, write a `.ps1` with OMP `write`, then run `pwsh.exe -NoProfile -NoLogo -NonInteractive -File "C:\path\script.ps1"`.
- If `pwsh.exe` is unavailable, fall back to `powershell.exe -NoProfile -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "C:\path\script.ps1"`.

Quoting and path rules:
- Do not put PowerShell `-Command` bodies inside Bash double quotes; Bash expands `$`, backticks, and backslashes first.
- Prefer single-quoted Bash wrapping for inline PowerShell scripts, or use `-File`.
- In PowerShell, use `$env:NAME` for environment variables, not Bash `$NAME`.
- Use `-LiteralPath` with quoted Windows paths.
- Do not point POSIX shell commands at `C:\...` or UNC paths. Use OMP `read`/`search`/`find`/`edit`/`write`, or use PowerShell with `-LiteralPath`.

Treat these as prohibited unless the user explicitly wants them and the risk is understood:
- `-EncodedCommand`
- `Start-Process`, `Invoke-Item`, `explorer`, `rundll32`, `mshta`, or browser/URL launch patterns
- forceful or recursive quiet delete patterns
