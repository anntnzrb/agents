# Skills Gate

## Executable skills

- Public entrypoint: `scripts/cli.py`
- Public invocation:
  ```text
  uv run --script <skill-dir>/scripts/cli.py ...
  ```
- Put runtime deps in PEP 723 metadata inside `scripts/cli.py`
- Put reusable code in `lib/<module>/`; make `scripts/cli.py` add `lib/` to `sys.path`
- Keep `SKILL.md` focused on when/how to use the skill; move bulk docs to `references/`
- Progressive disclosure standard:
  - `SKILL.md` is the entrypoint/router only: triggers, activation criteria, minimal workflow, tool/script routing, and follow-up reads
  - Target `SKILL.md` at ≤150 lines; hard cap 250 lines unless the skill has no bundled references
  - Move stable explanation/API notes to `references/`; move worked examples to `cookbook/`; move deterministic fetching/parsing/scoring/generation into `scripts/`
  - When bundled docs exist, `SKILL.md` MUST include a required follow-up reads table with columns: `Need`, `Read`, `When`
  - Reference files over 300 lines MUST start with a table of contents or equivalent section index
  - Do not place large always-loaded docs in skill-package `AGENTS.md`; use `references/` and route to them from `SKILL.md`

## Metadata Budget

- `name` and `description` frontmatter load during skill discovery; treat them as scarce shared context across harnesses
- Keep each `description` to one trigger-focused sentence of at most 120 characters. Preserve the capability and concrete trigger nouns; move workflow detail into `SKILL.md` or references
- Validate every changed skill with `quick-validate`; it enforces the 120-character description cap
- Before adding a skill, prune or consolidate overlapping skills if the inventory would exceed this budget. Do not trade context capacity for keyword soup

## Licensing

- Every `SKILL.md` declares `license: AGPL-3.0-or-later`, including `legacy/`; root `COPYING` holds the official text
- No license headers in non-Markdown files
- Before porting from another repo, read its license: MIT/Apache/BSD/GPL/AGPL port as AGPL with a `NOTICE.md` preserving upstream notices; CC BY-SA keeps attribution; no-license, BUSL, or CC BY-NC: do not port

## Model-facing text

- Treat skill bodies, loaded references, agent definitions, and tool descriptions as model-facing prompts
- Write dense, imperative prose. Keep one decision per bullet; delete ceremony, repetition, and predictable grammar
- Preserve negation, uncertainty, causality, conditions, quantities, temporal boundaries, permissions, proper nouns, and technical terms
- Use uppercase RFC 2119 keywords only for genuine requirements, prohibitions, or strong preferences. NEVER convert factual descriptions, schemas, code, or examples
- Use structural tags only when their names match real semantics. NEVER invent tags solely for emphasis
- Put critical constraints near the first decision they govern. Repeat them only when a long prompt could hide them
- Pair a prohibition with its positive alternative when the alternative is not obvious
- Keep tactical bullets short by splitting distinct claims; do not enforce an arbitrary word-count target
- Examples MUST use exact runnable syntax or clearly marked placeholders

## Tool and MCP prompt authoring

- Tool prompts teach when and why to use a tool, non-obvious input grammar, cross-tool routing, output caveats, and failures the agent can correct
- Let the machine-readable schema own field names, types, requiredness, enums, and ranges. Repeat schema mechanics only when the schema is unavailable or history proves the reminder prevents failures
- Focused skills own stable tool discovery: inline a compact inventory and exact common call shapes, then call known recipes directly
- Large stable surfaces use an inline routing index plus targeted reference sections; dynamic or unknown surfaces use a brief live inventory, then only the selected tool's schema
- Use dated full-schema snapshots only for broad selection or discovery failure; NEVER load a snapshot before an available targeted schema
- Input schemas do not imply output schemas. Only a published output schema is contractual; observed responses are samples
- Keep implementation internals, recovery machinery, caching, telemetry, and performance details out unless they change the agent's decision
- Worked examples MUST match the real call grammar. Anti-patterns MUST come from observed failures, not speculation
- Before deleting apparently redundant prompt text, inspect `git blame` and the relevant commit or issue. Failure-prevention scar tissue stays unless evidence supersedes it
- Schema inferability makes text a prune candidate, never an automatic deletion
- Automated overlap probes are OPTIONAL. They MUST use the actual wire schema and rendered prompt; provider-specific probes are not repository-wide requirements

## Portability Constraints

- Bundled skill entrypoints use `scripts/cli.py`, not Bash/sh/PowerShell wrappers
- Skills do not include `*.sh` files
- Public docs avoid `source`, `./script`, shebang, or executable-bit assumptions
- Public run paths use `uv run --script`, not raw `python`, `python3`, `pip`, or `pip install`
- Per-skill `pyproject.toml` or `uv.lock` belongs only in package-style skills when the user explicitly asks for package semantics
- Docs use `<temp-dir>` and code uses `tempfile`; avoid POSIX-only paths like `/tmp`

## Cross-platform code rules

- Use `pathlib.Path`, `tempfile`, and explicit encodings
- Use `subprocess.run([...], shell=False)` and preserve child exit codes
- Print human errors to stderr
- Return `2` for usage/config/platform errors
- Return `127` for missing required external executables
- Platform-specific skills must fail clearly on unsupported OS instead of relying on shell failure

## Full Gate

```
uvx ruff format <path>
uvx ruff check --select ALL --ignore COM812,D203,D213 <path>
```

## Validation

Use the `skill-creator` skill for skill creation, audits, packaging, or trigger/structure work.

Before handoff after skill executable changes:

```text
uv run --script <skill-dir>/scripts/cli.py --help
git diff --check
```

Before handoff after skill metadata changes:

```text
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate <changed-skill-dir>
git diff --check
```

For migrated library code, run the smallest relevant pytest/ruff/pyright gate with explicit `uv run --with ...` deps.

## Stop Rules

- Skip executable validation for docs-only edits unless the docs change public invocation behavior
- Do not add package metadata, shell wrappers, or platform assumptions unless the user explicitly requests that scope
