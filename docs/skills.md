# Manage shared skills

Use `skills/current/` for skills that sync publishes to enabled harnesses. Use `skills/legacy/` for archived skills. This page is the skill gate. It owns the workflow and authoring policy for shared skills.

## Change a skill

1. Read the policy sections below.
2. Edit `skills/current/<name>/`.
3. Run the skill's focused tests.
4. Run the validation that matches the changed files.
5. Run `uv run --project sync sync` from the repository root.
6. Inspect the generated skill in one harness home.

Keep development credentials in the root ignored `.env` file (`.env.example` at the repository root lists the shared template variables).

## Validate Python skills (standard)

All new skills and changed Python skills use the central code-gate runner in `skill-creator`. The runner executes Ruff format-check, Ruff strict linting (ALL with the sync exclusion set), Basedpyright in standard type-checking mode, and optionally pytest. Dependency environments for Basedpyright and pytest are derived automatically from the PEP 723 block in `scripts/cli.py`.

Run static checks (Ruff format-check, Ruff lint, Basedpyright):

```bash
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/<name>
```

Run static checks and the skill's test suite:

```bash
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/<name> --tests
```

Each Python skill provides a `pyproject.toml` containing tool configuration only (no runtime dependencies):

```toml
[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["ALL"]
ignore = ["A002", "ANN401", "BLE001", "COM812", "D203", "D213", "EM101", "EM102", "ERA001", "PERF401", "PLR0911", "PLR0912", "S101", "S603", "S607", "SLF001", "TRY003", "TRY301"]

[tool.ruff.lint.per-file-ignores]
"scripts/**/*.py" = ["T201"]
"tests/**/*.py" = ["S101"]

[tool.ruff.format]
quote-style = "double"

[tool.basedpyright]
typeCheckingMode = "standard"
include = ["scripts", "lib", "tests"]
pythonVersion = "3.12"
pythonPlatform = "All"
```

## Validate TypeScript and Bun skills (legacy / grandfathered)

TypeScript is grandfathered for existing skills (`market-hunter`, `omp-search`, `x-research`). New skills MUST use Python and `uv`. For changes to existing TypeScript skills, run the local test suite and compiler checks:

```bash
bun test skills/current/<name>
bunx tsc --project skills/current/<name>/tsconfig.json --noEmit
```

Run tests from the skill directory or repository root. Verify that TypeScript diagnostics return zero errors before handoff.
## Validate an executable skill

Executable skills use `scripts/cli.py` (Python) or `scripts/cli.ts` (TypeScript and Bun) as their public entrypoint. Check the command after changing executable behavior:

```bash
# Python executable skill
uv run --script skills/current/<name>/scripts/cli.py --help

# TypeScript and Bun executable skill
bun skills/current/<name>/scripts/cli.ts --help

git diff --check
```

Do not add a shell wrapper. For Python, put runtime dependencies in the PyPA inline script metadata (PEP 723) inside `scripts/cli.py`. For TypeScript and Bun, declare runtime dependencies in the skill's local `package.json`.

## Validate skill metadata

After changing `SKILL.md` frontmatter or package structure, run the repository validator:

```bash
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/<name>
git diff --check
```

See [Metadata budget](#metadata-budget) for the `description` constraint.

Use the `skill-creator` skill for skill creation, audits, packaging, or trigger/structure work.

## Archive a skill

Move the complete directory into `skills/legacy/`:

```bash
mv skills/current/<name> skills/legacy/<name>
uv run --project sync sync
```

The next sync removes the managed copy from harness homes. Sync does not publish anything under `skills/legacy/`.

## Skill package policy

- Public entrypoint: `scripts/cli.py`, invoked as `uv run --script <skill-dir>/scripts/cli.py ...`.
- Standalone `pyproject.toml` per skill with pinned dev tools; see Validate Python files.
- Put reusable code in `lib/<module>/`; make `scripts/cli.py` add `lib/` to `sys.path`.
- Declare inline dependencies in `scripts/cli.py` using PyPA inline script metadata (PEP 723 `# /// script` block).

### TypeScript and Bun skills
- Public entrypoint: `scripts/cli.ts`, invoked as `bun <skill-dir>/scripts/cli.ts ...`.
- Initialize the skill directory as an isolated package (`bun init` or local `package.json`) with pinned dependencies.
- Organize internal modules using Node and Bun package subpath imports (`#*` in `package.json` and matching `paths` in `tsconfig.json`, such as `#models`, `#config`, `#executor`) to eliminate relative `../` directory traversals.
- For Effect-based skills, use official Effect platform services (`FileSystem.FileSystem`, `Path.Path`, `effect/unstable/cli`), provide platform layers at the process entrypoint (`BunServices.layer`), and drive the top-level command with `BunRuntime.runMain`.

### Documentation structure
- Keep `SKILL.md` focused on when/how to use the skill; move bulk docs to `references/`.
- Progressive disclosure standard:
  - `SKILL.md` is the entrypoint/router only: triggers, activation criteria, minimal workflow, tool/script routing, and follow-up reads.
  - Target `SKILL.md` at ≤150 lines; hard cap 250 lines unless the skill has no bundled references.
  - Move stable explanation/API notes to `references/`; move worked examples to `cookbook/`; move deterministic fetching/parsing/scoring/generation into `scripts/`.
  - When bundled docs exist, `SKILL.md` MUST include a required follow-up reads table with columns: `Need`, `Read`, `When`.
  - Reference files over 300 lines MUST start with a table of contents or equivalent section index.
  - Do not place large always-loaded docs in skill-package `AGENTS.md`; use `references/` and route to them from `SKILL.md`.
- In `SKILL.md`, define the exact runnable entrypoint under `## Public entrypoint`. Worked examples in `## Common calls` and CLI `--help` text SHOULD use clean shorthand (e.g. `<command> <args>`) to minimize noise.

## Metadata budget

- `name` and `description` frontmatter load during skill discovery; treat them as scarce shared context across harnesses.
- Keep each `description` to one trigger-focused sentence of at most 120 characters. Preserve the capability and concrete trigger nouns; move workflow detail into `SKILL.md` or references.
- Validate every changed skill with `quick-validate`; it enforces the 120-character description cap.
- Before adding a skill, prune or consolidate overlapping skills if the inventory would exceed this budget. Do not trade context capacity for keyword soup.

## Licensing

- Every `SKILL.md` declares `license: AGPL-3.0-or-later`, including `legacy/`; root `COPYING` holds the official text.
- No license headers in non-Markdown files.
- Before porting from another repo, read its license: MIT/Apache/BSD/GPL/AGPL port as AGPL with a `NOTICE.md` preserving upstream notices; CC BY-SA keeps attribution; no-license, BUSL, or CC BY-NC: do not port.

## Model-facing text

- Treat skill bodies, loaded references, agent definitions, and tool descriptions as model-facing prompts.
- In Markdown and other prose files, NEVER use U+2013 (en dash) or U+2014 (em dash) in prose, examples, or tool descriptions. Use a period, comma, colon, or semicolon instead. Do not alter code, regexes, sentinel values, or fixtures to enforce this.
- Write dense, imperative prose. Keep one decision per bullet; delete ceremony, repetition, and predictable grammar.
- Preserve negation, uncertainty, causality, conditions, quantities, temporal boundaries, permissions, proper nouns, and technical terms.
- Use uppercase RFC 2119 keywords only for genuine requirements, prohibitions, or strong preferences. NEVER convert factual descriptions, schemas, code, or examples.
- Use structural tags only when their names match real semantics. NEVER invent tags solely for emphasis.
- Put critical constraints near the first decision they govern. Repeat them only when a long prompt could hide them.
- Pair a prohibition with its positive alternative when the alternative is not obvious.
- Keep tactical bullets short by splitting distinct claims; do not enforce an arbitrary word-count target.
- Examples MUST use exact runnable syntax or clearly marked placeholders.

## Tool and MCP prompt authoring

- Tool prompts teach when and why to use a tool, non-obvious input grammar, cross-tool routing, output caveats, and failures the agent can correct.
- Let the machine-readable schema own field names, types, requiredness, enums, and ranges. Repeat schema mechanics only when the schema is unavailable or history proves the reminder prevents failures.
- Focused skills own stable tool discovery: inline a compact inventory and exact common call shapes, then call known recipes directly.
- Large stable surfaces use an inline routing index plus targeted reference sections; dynamic or unknown surfaces use a brief live inventory, then only the selected tool's schema.
- Use dated full-schema snapshots only for broad selection or discovery failure; NEVER load a snapshot before an available targeted schema.
- Input schemas do not imply output schemas. Only a published output schema is contractual; observed responses are samples.
- Keep implementation internals, recovery machinery, caching, telemetry, and performance details out unless they change the agent's decision.
- Worked examples MUST match the real call grammar. Anti-patterns MUST come from observed failures, not speculation.
- Before deleting apparently redundant prompt text, inspect `git blame` and the relevant commit or issue. Failure-prevention scar tissue stays unless evidence supersedes it.
- Schema inferability makes text a prune candidate, never an automatic deletion.
- Automated overlap probes are OPTIONAL. They MUST use the actual wire schema and rendered prompt; provider-specific probes are not repository-wide requirements.

## Portability constraints

- Bundled skill entrypoints use `scripts/cli.py` (Python) or `scripts/cli.ts` (TypeScript and Bun), not Bash/sh/PowerShell wrappers.
- Skills do not include `*.sh` files.
- Public docs avoid `source`, `./script`, shebang, or executable-bit assumptions.
- Public run paths use `uv run --script` for Python and `bun <skill-dir>/scripts/cli.ts` for TypeScript; do not invoke raw `python`, `python3`, `pip`, `node`, or `npm`.
- Never bridge across repository directories with upward-traversing `tsconfig.json` path hacks.
- Docs use `<temp-dir>` and code uses `tempfile` or platform temp directories; avoid POSIX-only paths like `/tmp`.
- Skill scripts, default headers (e.g. `User-Agent`), and prompt templates MUST NOT contain personal usernames, machine hostnames, or private URLs.

## Cross-platform code rules

### Python code
- Use `pathlib.Path`, `tempfile`, and explicit encodings.
- Use `subprocess.run([...], shell=False)` and preserve child exit codes.

### TypeScript and Effect code
- Use `FileSystem.FileSystem` and `Path.Path` instead of `node:fs` or `node:path`.
- When bridging timers into `Promise.race` or Effect promises, always unreference timer handles (`timer.unref?.()`) and clear them (`clearTimeout(timer)`) on settlement to prevent hanging the event loop.
- When spawning non-interactive child processes, pass `stdin: "ignore"` to avoid blocking on standard input pipes.

### Common exit code conventions
- Print human errors to stderr.
- Return `0` for successful execution.
- Return `1` for runtime, network, or external service errors.
- Return `2` for usage, configuration, or platform errors.
- Return `124` when an outer execution timeout fires.
- Return `127` for missing required external executables.
- Platform-specific skills must fail clearly on unsupported OS instead of relying on shell failure.

## Final authoring review

Before handoff after any skill change:

1. Load `technical-writing`. Apply its plain-language, sentence, ambiguity, naming, and document-mode checks to changed model-facing prose.
2. Load `pstack-principles`. Read every leaf principle that matches the change; applying a principle from the index alone is forbidden. Use the principles to minimize the diff, keep boundaries explicit, remove unnecessary structure, and choose direct verification. In the handoff, name each applied principle and the decision it changed.
3. Load `unslop`. Apply prose mode to changed model-facing text. Apply code mode only when the requested work includes bounded, behavior-preserving cleanup; never use cleanup as permission to change feature behavior or widen scope.
4. Fix every applicable finding.
5. Rerun `quick-validate`, executable checks, and `git diff --check` as required above.
6. Scan the changed Markdown files for U+2013 or U+2014 with `rg -n '\x{2013}|\x{2014}' docs/skills.md`. The scan must return no matches.

## Stop rules

- Skip executable validation for docs-only edits unless the docs change public invocation behavior.
- Do not add package metadata, shell wrappers, or platform assumptions unless the user explicitly requests that scope.
