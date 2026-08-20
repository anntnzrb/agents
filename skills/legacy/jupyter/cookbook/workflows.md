# Workflows Cookbook

Common notebook workflows.

## Full edit→execute→verify

```bash
# 1. Inspect current state
uv run --script <skill-dir>/scripts/cli.py inspect notebook.ipynb

# 2. Edit cell (use NotebookEdit tool in Claude)

# 3. Execute and save outputs
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -i

# 4. View outputs
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb --output-only

# 5. If errors, check specific cell
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 5 -o
```

`-i` saves outputs in place for persistence.

## Execute cell range

Cells 3-7 example:

```bash
# Execute cells 3 through 7
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -c 3-7 -i

# View just those outputs
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 3-7 --output-only
```

Cell indices are 0-based; use `inspect` first to see the cell list.

## Prepare notebook for Git

```bash
# Validate syntax
uv run --script <skill-dir>/scripts/cli.py validate notebook.ipynb

# Clear all outputs
uv run --script <skill-dir>/scripts/cli.py clear notebook.ipynb

# Now safe to commit
git add notebook.ipynb
```

A pre-commit hook can run `clear` automatically.

## Convert notebook→Python

```bash
# Convert to .py file
uv run --script <skill-dir>/scripts/cli.py convert notebook.ipynb --to py -o script.py
```

Output includes cell-marker comments for reference.

## Generate HTML report

Ensure outputs are current, then convert:

```bash
# First ensure outputs are current
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -i

# Then convert to HTML
uv run --script <skill-dir>/scripts/cli.py convert notebook.ipynb --to html -o report.html
```

PDF: use `--to pdf`; additional system dependencies required.

## Debug import errors

Execute import cells and inspect errors:

```bash
# Execute just the import cells
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -c 0-2 --allow-errors

# Check the error
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 0-2 -o
```

Error output identifies the missing package with `ModuleNotFoundError`.

## Incremental execution

```bash
# Execute in batches
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -c 0-5 -i
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 5 -o

# If good, continue
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb -c 6-10 -i
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 10 -o
```

Use `--allow-errors` to continue past failures.

## Extract code

```bash
# Show only code cells
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -t code
```

Use `-t markdown` for only markdown cells.

## Check notebook health

```bash
# Quick syntax validation
uv run --script <skill-dir>/scripts/cli.py validate notebook.ipynb

# Check if all cells have been executed
uv run --script <skill-dir>/scripts/cli.py validate notebook.ipynb --require-outputs
```

Fix syntax errors before execution to avoid cryptic kernel errors.

## View raw output data

For output JSON structure and display debugging:

```bash
# Show raw output data
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 5 -o --raw
```

Raw mode shows full MIME-type data, including base64-encoded images.

## Find cells by pattern

```bash
# Find cells importing pandas
uv run --script <skill-dir>/scripts/cli.py grep "import pandas" notebook.ipynb

# Find function definitions (case-insensitive regex)
uv run --script <skill-dir>/scripts/cli.py grep -i "def.*process" notebook.ipynb

# Show full cell context around matches
uv run --script <skill-dir>/scripts/cli.py grep -C "class.*Model" notebook.ipynb

# Get just cell indices (for piping to execute)
uv run --script <skill-dir>/scripts/cli.py grep --cells-only "TODO" notebook.ipynb
```

Pass returned `--cells-only` indices to `execute -c <indices>`.

## Extract images

```bash
# Save all images from outputs to a directory
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -o --save-images <images-dir>

# Save images after executing
uv run --script <skill-dir>/scripts/cli.py execute notebook.ipynb --save-images <outputs-dir>

# Extract images from specific cells only
uv run --script <skill-dir>/scripts/cli.py show notebook.ipynb -c 5,10-12 -o --save-images <figures-dir>
```

Images save as `cell_N_output_M.png` (or `.jpg`, `.svg`). PNG, JPEG, and SVG supported.
