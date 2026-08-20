---
name: jupyter
description: "Use when .ipynb files or Jupyter notebooks must be executed, inspected, validated, converted, or debugged."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Jupyter Notebook Skill

Claude Code can execute, inspect, and manage Jupyter notebooks directly, avoiding CLI/browser context switching.

## Workflow

```
1. INSPECT  → Understand notebook structure (`uv run --script <skill-dir>/scripts/cli.py inspect`)
2. EDIT     → Modify cells with NotebookEdit tool
3. EXECUTE  → Run cells and capture outputs (`uv run --script <skill-dir>/scripts/cli.py execute -i`)
4. VERIFY   → Read outputs, check for errors (`uv run --script <skill-dir>/scripts/cli.py show --output-only`)
5. ITERATE  → Repeat until complete
```

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Setup (One-Time)

```bash
# Install a Jupyter kernel (needed for execution)
uv run --with ipykernel python -m ipykernel install --user --name uv-py
```

## Scripts

Public dispatcher: `scripts/cli.py`.

|Command|Purpose|Internal|
|---|---|---|
|`inspect`, `show`, `execute`, `convert`, `clear`, `grep`|Full notebook CLI|`nb.py`|
|`validate`|Quick syntax check|`validate.py`|

`cli.py` carries inline dependencies (PEP 723); uv handles everything automatically.

## CLI Reference

```bash
# Inspect structure
uv run --script <skill-dir>/scripts/cli.py inspect notebook.ipynb

# Show cell contents
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 0,2-4      # specific cells
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -o            # include outputs
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb --output-only # outputs only
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -o --save-images <images-dir>

# Execute cells
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb            # all cells, show output
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -i         # save outputs back to file
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -c 0,2-4   # specific cells
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb --save-images <outputs-dir>

# Search cells
uv run --script <skill-dir>/scripts/cli.py grep "import pandas" notebook.ipynb      # find cells with pattern
uv run --script <skill-dir>/scripts/cli.py grep -i "def.*function" notebook.ipynb   # case-insensitive regex
uv run --script <skill-dir>/scripts/cli.py grep -C "pattern" notebook.ipynb         # show full cell context
uv run --script <skill-dir>/scripts/cli.py grep --cells-only "pattern" notebook.ipynb  # just cell indices

# Validate (lightweight)
uv run --script <skill-dir>/scripts/cli.py validate notebook.ipynb

# Convert
uv run --script <skill-dir>/scripts/cli.py convert notebook.ipynb --to py
uv run --script <skill-dir>/scripts/cli.py convert notebook.ipynb --to html -o output.html

# Clear outputs
uv run --script <skill-dir>/scripts/cli.py clear notebook.ipynb
```

## Quick Patterns

### Execute and Read Outputs (No Browser Needed)

```bash
# Execute all cells, save outputs back to file
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -i

# Then show just the outputs
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb --output-only
```

### Debug a Failing Cell

```bash
# Execute up to the failing cell
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -c 0-5 --allow-errors

# Inspect the error output
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 5 -o
```

### Edit Cell (Built-in Tool)

`NotebookEdit` parameters:
- `cell_id`: The cell ID or index
- `new_source`: New cell content
- `edit_mode`: "replace", "insert", or "delete"
- `cell_type`: "code" or "markdown"

### Validate Before Commit

```bash
# Quick syntax check
uv run --script <skill-dir>/scripts/cli.py validate notebook.ipynb

# Clear outputs for clean commits
uv run --script <skill-dir>/scripts/cli.py clear notebook.ipynb
```

Cell contents: `uv run --script <skill-dir>/scripts/cli.py show` or `read` tool.
Outputs: `uv run --script <skill-dir>/scripts/cli.py show -o` or `--output-only`.
Images: `uv run --script <skill-dir>/scripts/cli.py show -o --save-images DIR`.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Notebook structure and execution model|`reference.md`|Before structural edits or execution design|
|Common notebook workflows|`cookbook/workflows.md`|When a documented workflow matches|
|Errors and recovery|`cookbook/troubleshooting.md`|After execution, kernel, or format failure|
