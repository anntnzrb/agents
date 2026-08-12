# Jupyter Reference

MUST read before structural notebook edits or execution design.

## Notebook structure (nbformat v4)

`.ipynb`: JSON with this shape:

```json
{
  "metadata": {
    "kernelspec": {"name": "python3", "display_name": "Python 3"},
    "language_info": {"name": "python", "version": "3.11"}
  },
  "nbformat": 4,
  "nbformat_minor": 5,
  "cells": [...]
}
```

### Cell types

Code cell:

```json
{
  "cell_type": "code",
  "id": "unique-id",
  "source": "print('hello')",
  "metadata": {},
  "execution_count": 1,
  "outputs": [...]
}
```

Markdown cell:

```json
{
  "cell_type": "markdown",
  "id": "unique-id",
  "source": "# Heading",
  "metadata": {}
}
```

### Output types

`stream`: `text` — stdout/stderr.
`execute_result`: `data` — last expression's return value.
`display_data`: `data` — explicit plots, HTML, etc.
`error`: `ename`, `evalue`, `traceback` — exception information.

### Data MIME types

`text/plain` — text representation; `text/html` — tables/rich output; `image/png` — PNG, base64 encoded; `image/svg+xml` — SVG; `application/json` — JSON.

## Execution model

Kernel lifecycle: start kernel (initialize Python interpreter) → execute cells in order (state persists) → capture stdout, stderr, and display data → store results in notebook.

Cells share state; variables persist across cells. Execution order matters: earlier cells must run first. “Restart and Run All” ensures clean state.

Common kernel names:

|Name|Description|
|---|---|
|`python3`|Default Python 3 kernel|
|`python`|May be Python 2 or 3|
|`ir`|R kernel|
|`julia-1.9`|Julia kernel|

## Best practices

Clean notebooks:

1. Clear outputs before commit — manageable diffs.
2. Restart kernel regularly — avoid hidden-state bugs.
3. Run all cells in order — verify end-to-end operation.
4. Use markdown headers — navigation structure.

Reproducibility:

1. Pin dependencies in first cell.
2. Set random seeds.
3. Avoid external state; do not depend on prior runs.
4. Document assumptions and data sources.

Cell granularity:

|Good|Bad|
|---|---|
|One concept per cell|Giant cells with many operations|
|Imports in first cell|Imports scattered throughout|
|Markdown before code|Code without explanation|
|Small, testable units|Monolithic scripts|

## Anti-patterns

### State confusion

```python
# Cell 1
x = 10

# Cell 2
print(x)  # Works if Cell 1 ran

# Cell 3 (user runs this first)
y = x + 1  # NameError: x not defined
```

Fix: Restart kernel and “Run All” to verify order-independence.

### Hidden state

```python
# Cell 1
data = load_data()  # Takes 5 minutes

# Cell 2 (modified)
result = process(data)  # Uses stale 'data' from old Cell 1
```

Fix: Re-run upstream cells after modifications.

### Output bloat

```python
# Avoid: Giant outputs that inflate notebook size
df  # Displays entire dataframe

# Better: Limit output
df.head()
df.describe()
```

## Cell addressing

### By index (0-based)

```bash
# Show cell 0
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 0

# Show cells 2, 3, 4
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 2-4

# Show cells 0, 5, 10
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 0,5,10
```

### By cell ID

Each cell has a unique `id`; `NotebookEdit` targets a specific cell:

```python
# NotebookEdit parameters
cell_id = "abc123"  # Targets specific cell
```

## Kernel management

### Timeout handling

Long-running cells may timeout. Adjust with `-t`:

```bash
# 10-minute timeout (default: 600s)
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -t 600

# 1-hour timeout for ML training
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -t 3600
```

### Kernel selection

Force a specific kernel with `-k`:

```bash
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -k uv-py
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -k ir  # R kernel
```

### Error handling

Continue past failing cells with `--allow-errors`:

```bash
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb --allow-errors
```

## Output interpretation

### Stream output

```json
{ "output_type": "stream", "name": "stdout", "text": "Hello\n" }
```

Displayed as plain text.

### Execute result

```json
{
  "output_type": "execute_result",
  "data": {
    "text/plain": "42",
    "text/html": "<b>42</b>"
  }
}
```

`text/plain` shown by default. Use `--raw` for full data.

### Error output

```json
{
  "output_type": "error",
  "ename": "ValueError",
  "evalue": "invalid literal",
  "traceback": ["..."]
}
```

Traceback displayed with ANSI codes stripped.
