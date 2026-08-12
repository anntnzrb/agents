# Troubleshooting Cookbook

Use when binary resolution, quoting, language parsing, or pattern searches fail.

## `sg` not found

`sg` command missing.

```bash
ast-grep run -p 'pattern' -l ts src
```

If not installed:

```bash
nix run nixpkgs#ast-grep -- run -p 'pattern' -l ts src
```

## No matches

Expected matches absent:

```bash
sg -p 'pattern' -l ts --debug-query=ast
```

Verify `--lang`; try `--strictness=relaxed`.

## Wrong language detection

Files parsed as the wrong language:

```bash
sg -p 'pattern' -l ts path/to/file
```

Force `--lang` for generated or unusual extensions.

## Too many matches

Pattern too broad:

```bash
sg -p 'pattern' -l ts --selector identifier src
```

Add structure or use `--strictness=cst`.

## Slow search

Search takes too long:

```bash
sg -p 'pattern' -l ts --globs 'src/**/*.ts' --threads 4 .
```

Limit paths; exclude large directories with `--globs '!**/dist/**'`.

## Stdin errors

Stdin search fails:

```bash
cat file.ts | sg -p 'pattern' -l ts --stdin
```

`--lang` required; interactive mode incompatible with stdin.
