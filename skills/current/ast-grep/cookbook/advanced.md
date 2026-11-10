# Advanced Cookbook

Higher-signal queries; structural selectors, relationships, precise scope control.

## Sub-node selector
Match a call expression inside a larger pattern:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'if ($COND) { $BODY }' --selector call_expression -l ts src
```

`--debug-query=ast` shows node kinds.

## Pattern parsing
Pattern does not match → inspect structure:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'await $CALL($$$)' -l ts --debug-query=ast
```

Punctuation matters → try `--debug-query=cst`.

## Matching strictness
Over- or under-matching:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p '$A && $A()' -l ts --strictness=ast src
```

`relaxed` ignores comments; `cst` is strict.

## Globs
Search only `src` TypeScript and exclude tests:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'new $TYPE($$$)' -l ts --globs 'src/**/*.ts' --globs '!**/*.test.ts' .
```

Later globs override earlier ones.

## File list
Restrict search to known files; cheap prefilter cuts parse cost:

```bash
rg -l "console\\.log" src | xargs uv run --script <skill-dir>/scripts/cli.py run -p 'console.log($$$)' -l ts
```

## Compact JSON
Emit minimal JSON for tooling:

```bash
uv run --script <skill-dir>/scripts/cli.py run -p 'new $TYPE($$$)' -l ts --json=compact src
```

For paths only, use `--files-with-matches` instead of `--json`; the flags conflict.
