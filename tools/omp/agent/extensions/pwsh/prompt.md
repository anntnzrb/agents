Execute Windows-native shell commands with PowerShell / PowerShell Core.

Use this tool for shell work in Windows sessions. Returns merged stdout/stderr. Use `cwd` to set the working directory, `env` for extra environment variables, and `timeout` for long-running commands. Use PowerShell syntax, not bash syntax.

PowerShell rules:
- Prefer built-in cmdlets: `Get-ChildItem`, `Get-Content`, `Select-String`, `New-Item`, `Remove-Item`, `Copy-Item`, `Move-Item`.
- Prefer `-LiteralPath` for paths with spaces, brackets, wildcard characters, or Unicode.
- Environment variables use `$env:NAME`.
- Prefer single-quoted strings for literal text.
- Prefer here-strings for multiline or quote-heavy commands.
- Use `${var}` when interpolating variables next to punctuation.
- Use PowerShell pipelines that pass objects, not text unless text is required.
- Do not use Unix-only shell operators or coreutils when dedicated OMP tools (`read`, `find`, `search`, `write`, `edit`) are better.
- Do not use bash-only redirection, quoting, globbing, or env assignment syntax.
