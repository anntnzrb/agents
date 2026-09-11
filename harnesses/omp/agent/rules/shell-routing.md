---
name: shell-routing
description: Prefer dedicated file and search tools over their shell equivalents; keep bash when the shell is doing real work
condition:
  - '(?:[;&"]\s*)(?:cat|head|tail|less|more)\s+\S'
  - '(?:[;&"]\s*)(?:grep|rg|ripgrep|ag|ack)\s+\S'
  - '(?:[;&"]\s*)(?:find|fd|locate)\s+\S'
  - '(?:[;&"]\s*)(?:sed|perl)\s+(?:-[A-Za-z]*i\b|--in-place)'
  - '(?:[;&"]\s*)sed\s+(?:-[A-Za-z]*n\b|--quiet)'
  - '(?:[;&"]\s*)awk\s+[^"]*-i\s+inplace'
scope:
  - tool:bash
interruptMode: never
---
# Shell routing

Prefer the dedicated tool when it can express the operation. Keep bash when the shell is doing real work: pipelines, redirection, loops, process control, or paths that only exist after variable expansion.

- **Reading files.** Use `read` (`path:10-50` line selectors) instead of `cat`/`head`/`tail`/`less`. It anchors line numbers and handles binary, archive, and document input. Stay in bash when the output is piped or aggregated (`cat *.md | wc -w`) or the path needs shell expansion (`$PI/dist/cli.js`).
- **Searching contents.** Use `grep` instead of `grep`/`rg`/`ag`: it respects `.gitignore`, groups by file, and paginates. Keep bash for piped stdin (`printf x | grep x`) and for post-processing hits (`| head`, `| jq`).
- **Finding paths.** Use `glob` instead of `find`/`fd` for name, type, and glob patterns. Keep `find` for predicates `glob` cannot express: `-maxdepth`, `-type d`, `\( -iname a -o -iname b \)`, `-newer`, `-exec`.
- **Editing.** Use `edit` (diff preview, fuzzy match, hashline anchors) instead of `sed -i`, `perl -i`, or `awk -i inplace`. Use `write` to author a file instead of `echo`/`printf` redirects or `cat <<EOF >`; `chmod` afterwards for scripts.
- **Reading a line range.** Use `read` with a selector (`src/foo.ts:470-530`) instead of `sed -n '470,530p'`. `read` cannot expand shell variables, so a `$VAR` path stays in bash.
