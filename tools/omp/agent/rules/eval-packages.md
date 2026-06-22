---
name: eval-packages
condition:
  - "(?:pip|pip3)(?:\\d+(?:\\.\\d+)*)?\\s+\\w*\\s*install"
  - "ModuleNotFoundError|ImportError"
scope:
  - text
  - thinking
interruptMode: always
description: >
  Redirect pip/pip3 install commands and missing-module errors to the managed
  uv pip workflow for the OMP eval Python kernel.
---
Eval cell failed with missing package. Fix: `uv pip list --python ~/.omp/python-env/bin/python3 | grep <pkg> || uv pip install --python ~/.omp/python-env/bin/python3 <pkg>`, then re-run eval. No forfeit — fix and retry. No raw pip/pip3/python -m pip.
