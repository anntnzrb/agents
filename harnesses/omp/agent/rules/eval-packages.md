---
name: eval-packages
condition:
  - "ModuleNotFoundError|ImportError"
scope:
  - text
  - thinking
interruptMode: always
description: >
  Redirect missing-module errors to the managed uv pip workflow for the OMP
  eval Python kernel. Raw pip/pip3 commands are handled by bash interceptors.
---
Eval cell failed with a missing package. Fix: `uv pip list --python ~/.omp/python-env/bin/python3 | grep <pkg> || uv pip install --python ~/.omp/python-env/bin/python3 <pkg>`, then re-run eval. No forfeit; fix and retry. No raw pip/pip3/python -m pip.
