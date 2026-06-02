---
name: xml-surgeon
description: Targeted XML read/write edits with XPath, minimal formatting changes, and batch operations across many files. Use for any XML work where precise, surgical reads and changes are needed, including subtree inspection, child-node scanning, attribute/text updates, insert/replace/delete of nodes, and multi-file refactors. Prefer this skill over generic read/edit tools whenever working with XML files.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Xml Surgeon

## Overview

Use `scripts/cli.py` for XPath-based XML reads/edits with minimal formatting drift. Prefer dry-run + diff, then in-place write.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Quick start

- Inspect matches:
  - `uv run --script <skill-dir>/scripts/cli.py select --xpath "//field[@name='arch']" path/to/file.xml`
- Read text or attr:
  - `uv run --script <skill-dir>/scripts/cli.py get --xpath "//field[@name='name']" path/to/file.xml`
  - `uv run --script <skill-dir>/scripts/cli.py get --xpath "//record" --attr id path/to/file.xml`
- Show subtree or inner XML:
  - `uv run --script <skill-dir>/scripts/cli.py show --xpath "//record[@id='view_form']" path/to/file.xml`
  - `uv run --script <skill-dir>/scripts/cli.py show --xpath "//field[@name='arch']" --inner --max-chars 2000 path/to/file.xml`
- Scan child nodes:
  - `uv run --script <skill-dir>/scripts/cli.py children --xpath "//group" path/to/file.xml`
  - `uv run --script <skill-dir>/scripts/cli.py children --xpath "//group" --list --attrs path/to/file.xml`
- Outline structure:
  - `uv run --script <skill-dir>/scripts/cli.py outline --xpath "//record[@model='ir.ui.view']" --depth 3 path/to/file.xml`
  - `uv run --script <skill-dir>/scripts/cli.py outline --xpath "//record[@id='view_form']" --attr id --attr name path/to/file.xml`
- Context around matches:
  - `uv run --script <skill-dir>/scripts/cli.py context --xpath "//field[@name='arch']" --before 2 --after 6 path/to/file.xml`
- Set attribute (dry-run + diff):
  - `uv run --script <skill-dir>/scripts/cli.py set-attr --xpath "//field[@name='arch']" --name string --value my_label --diff path/to/file.xml`
  - add `--in-place` to write
- Set text from file:
  - `uv run --script <skill-dir>/scripts/cli.py set-text --xpath "//field[@name='arch']" --value-file snippet.xml --diff path/to/file.xml`
- Insert XML fragment:
  - `uv run --script <skill-dir>/scripts/cli.py insert --xpath "//group" --position inside-last --xml "<field name='x'/>" --diff --reformat-ok path/to/file.xml`
- Delete nodes:
  - `uv run --script <skill-dir>/scripts/cli.py delete --xpath "//field[@name='x']" --diff --reformat-ok path/to/file.xml`

## Workflow

- Inspect: `select` for match counts and sourcelines
- Read: `show`, `children`, `outline`, or `context` for subtree/structure scanning
- Dry-run: run mutating commands with `--diff` (no `--in-place`)
- Apply: add `--in-place` after diff looks tight
- Verify: spot-check with `select` or `get`

## Tasks

- Inspect/select: use `select`, `get`, `show`, `children`, `outline`, and `context` for precise targeting
- Attribute edits: `set-attr`, `del-attr`
- Text edits: `set-text` with `--value` or `--value-file`
- Structural edits: `insert`, `replace`, `delete` with XPath
- Batch edits: pass multiple paths or globs (e.g., `**/*.xml`)

## Guardrails

- Minimal diffs: `set-attr`, `del-attr`, and `set-text` are surgical and preserve formatting
- Structural edits: `insert`, `replace`, `delete` reserialize XML and can reformat; require `--reformat-ok`
- Large files: use `--huge` if parser complains
- Namespaces: pass `--ns prefix=uri` and use `prefix:tag` in XPath
- Indentation drift: use `--indent` on insert/replace if needed

## Resources

- `scripts/cli.py`: public dispatcher
- `scripts/main.py`: internal XML edit tool
- `scripts/lib.py`: helper module used by the CLI
- `references/xml-surgeon.md`: XPath tips, minimal-diff notes, large-file hints
