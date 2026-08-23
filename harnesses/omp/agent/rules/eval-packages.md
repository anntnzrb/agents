---
name: eval-packages
condition:
  - "ModuleNotFoundError|ImportError|Cannot find (?:module|package)|ERR_MODULE_NOT_FOUND"
  - "\\b(?:update|upgrade|install|add)\\b.*\\b(?:eval|kernel|python-env|node_modules)\\s+packages?\\b"
scope:
  - text
  - thinking
interruptMode: always
description: >
  Managed package installation, updates, and import-recovery workflows for OMP
  eval kernels (Python in ~/.omp/python-env and JS in ~/node_modules).
---
Package workflow for OMP eval kernels:

- **Python (`py`)**:
  - Install: `uv pip install --python ~/.omp/python-env/bin/python <pkg>`
  - Update single: `uv pip install -U --python ~/.omp/python-env/bin/python <pkg>`
  - Update all: `uv pip install --upgrade --python ~/.omp/python-env/bin/python $(uv pip list --python ~/.omp/python-env/bin/python --format freeze | cut -d= -f1)`
  - No raw `pip`/`pip3`/`python -m pip`.

- **JavaScript (`js`)**:
  - Install global fallback: `cd ~ && bun add <pkg>`
  - Update all global: `cd ~ && bun update --latest`
  - Reset eval worker after install/update: `eval(language="js", reset=true, ...)`

Eval cell failed with missing package: install using matching kernel workflow above, then re-run eval (no forfeit; fix and retry).
