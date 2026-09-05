---
name: eval-packages
condition:
  - '\b(?:import\s+|from\s+[A-Za-z_][\w.]*\s+import\b|__import__\s*\(|importlib\.import_module\s*\()'
  - '\buv\s+pip\s+(?:install|uninstall)\b[^\n]*--python\s+[^\n]*python-env'
scope:
  - tool:eval
  - tool:bash
interruptMode: never
description: Keep OMP kernel dependency recovery scoped to the failing environment and authorized changes
---
This reminder does not mean an import failed or authorize an installation.

- Recover dependencies only after an actual kernel failure or an explicit environment-maintenance request. Quoted errors and project import failures do not establish a missing OMP kernel dependency.
- Identify the failing interpreter, package, and environment first. An `ImportError` may indicate an incompatible API, not a missing distribution.
- Preserve read-only and discussion mode. Obtain approval when the task does not authorize environment changes. Never install, uninstall, or upgrade packages merely because this rule fired.
- For an authorized Python kernel installation, use `bash` with `uv pip install --python <kernel-python> <package>`. Resolve the actual kernel interpreter rather than assuming a project virtual environment or hard-coded home.
- Change only the required package. Do not upgrade all packages or create a global JavaScript package environment as an import fallback. Use only runtimes supported by the active tool schema.
- After an authorized repair, retry the failed import or cell. Preserve existing kernel state; reset only when required and account for lost state.
