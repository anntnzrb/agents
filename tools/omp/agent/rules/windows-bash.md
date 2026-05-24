---
description: Windows shell policy for the OMP bash tool
alwaysApply: true
---

On Windows, OMP's `bash` tool is Git Bash/MSYS-style Bash, not PowerShell.

When the task is Windows-native shell work:
- Call `pwsh.exe` explicitly from `bash` instead of typing PowerShell cmdlets directly into Bash.
- Prefer: `pwsh.exe -NoProfile -NoLogo -NonInteractive -Command '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; <script>'`
- For multiline or quote-heavy commands, reserve a temp script path in PowerShell's temp directory, write the `.ps1` with OMP `write`, then run `pwsh.exe -NoProfile -NoLogo -NonInteractive -File "<temp-script-path>"`.
- If `pwsh.exe` is unavailable, fall back to `powershell.exe -NoProfile -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "C:\path\script.ps1"`.

For temporary `.ps1` scripts, do **not** throw files into the current working directory. Use a PowerShell-native temp path instead:

```powershell
$tmp = New-TemporaryFile
$script = [System.IO.Path]::ChangeExtension($tmp.FullName, '.ps1')
Move-Item -LiteralPath $tmp.FullName -Destination $script
$script
```

Then:
- write script content to that temp `.ps1` path with OMP `write`
- run it with `pwsh.exe -NoProfile -NoLogo -NonInteractive -File "<temp-script-path>"`
- clean it up afterwards with `Remove-Item -LiteralPath '<temp-script-path>'`

Quoting and path rules:
- Do not put PowerShell `-Command` bodies inside Bash double quotes; Bash expands `$`, backticks, and backslashes first.
- Prefer single-quoted Bash wrapping for inline PowerShell scripts, or use `-File`.
- In PowerShell, use `$env:NAME` for environment variables, not Bash `$NAME`.
- Use `-LiteralPath` with quoted Windows paths.
- `New-TemporaryFile` uses PowerShell's temp directory (`TMP`, then `TEMP`, then `USERPROFILE`, then the Windows directory on Windows), so prefer it over ad-hoc working-directory script files.
- Do not point POSIX shell commands at `C:\...` or UNC paths. Use OMP `read`/`search`/`find`/`edit`/`write`, or use PowerShell with `-LiteralPath`.

Treat these as prohibited unless the user explicitly wants them and the risk is understood:
- `-EncodedCommand`
- `Start-Process`, `Invoke-Item`, `explorer`, `rundll32`, `mshta`, or browser/URL launch patterns
- forceful or recursive quiet delete patterns
