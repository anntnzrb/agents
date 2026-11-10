# Basics Cookbook

Read-only recipes for fast code exploration.

## Find call sites
Find all `console.log` calls in TS:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'console.log($$$)' -l ts src
```

Quick file list: add `--files-with-matches`.

## Find a pattern across repo
Find `if ($A) { $B }` patterns in JS:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'if ($A) { $B }' -l js .
```

Add `-C 2` for context.

## Find function declarations
List JS/TS function declarations:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'function $NAME($$$) { $$$ }' -l ts src
```

Fast index: add `--files-with-matches`.

## Find Python defs
Find Python function definitions:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'def $NAME($$$): $$$' -l py src
```

See signature context: add `-C 1`.

## Stream JSON to other tools
Pipe matches to another script:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'new $TYPE($$$)' -l ts --json=stream src
```

`--json=stream`: one JSON object per line.

## Use stdin safely
Search a snippet from stdin:

```bash
cat snippet.ts | uv run --script <skill-dir>/scripts/cli.py run -p 'await $CALL($$$)' -l ts --stdin
```

`--lang` required for stdin.
