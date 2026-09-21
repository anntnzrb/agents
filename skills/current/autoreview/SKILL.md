---
name: autoreview
description: "Use when evaluating git diffs, commits, or pull requests for invariant violations, security bugs, or regressions."
license: AGPL-3.0-or-later
metadata:
  version: "1.0.0"
  author: openclaw
---

# AutoReview

Production-grade code review harness performing deterministic preflight checks (sensitive path redaction, multi-state Git target resolution) and structured invariant analysis across arbitrary languages and diffs.

## Entry Point

Invoke the standalone CLI via `uv`:

```sh
uv run --script <skill-dir>/scripts/cli.py [options]
```

## Git Review Targets

| Target | Arguments | Scope |
| :--- | :--- | :--- |
| **Local Work** *(Default)* | `--mode local` | `HEAD` $\to$ `index` $\to$ working tree, plus untracked text files |
| **Pinned Merge Base** | `--mode local --base <ref>` | Base commit $\to$ index $\to$ working tree (ideal for dirty PR candidates) |
| **Committed Branch / PR** | `--mode branch --base <ref>` | `merge-base(base, HEAD)` $\to$ `HEAD` (excludes uncommitted edits) |
| **Single Commit** | `--mode commit --commit <sha>` | Raw parent $\to$ commit (root compares against empty tree) |
| **Automatic** | `--mode auto` | Local work if working tree is dirty; falls back to branch mode against PR base or `origin/main` |

## Severity and Priority Thresholds

Findings are categorized into standard priority levels:
- **`P0` (Blocker / Critical)**: Data loss, active exploit, broken invariant, or fatal startup crashes.
- **`P1` (High / Severe)**: Logic bugs on common paths, unhandled error cases, or major regressions.
- **`P2` (Medium / Moderate)**: Edge-case defects, missing tests, or performance degradations.
- **`P3` (Low / Minor)**: Maintainability debt or minor improvements.

Set the reporting threshold via `--max-priority`:
```sh
uv run --script <skill-dir>/scripts/cli.py --mode local --max-priority P1
```

## Common Operations

### 1. Review Uncommitted / Staged Changes
```sh
uv run --script <skill-dir>/scripts/cli.py --mode local
```

### 2. Review a Branch against `origin/main`
```sh
uv run --script <skill-dir>/scripts/cli.py --mode branch --base origin/main
```

### 3. Review a Specific Commit with JSON Output
```sh
uv run --script <skill-dir>/scripts/cli.py --mode commit --commit HEAD --json-output review.json
```

## Output Contract

When invoked with `--json-output <path>`, the tool emits a structured payload:
```json
{
  "summary": "Review summary and general assessment",
  "overall_correctness": "patch is correct | patch is incorrect",
  "findings": [
    {
      "title": "Short title (1-140 chars)",
      "body": "Detailed actionable explanation",
      "priority": "P0 | P1 | P2 | P3",
      "confidence": 0.95,
      "category": "bug | security | regression | test_gap | maintainability",
      "code_location": {
        "file_path": "path/to/file.ts",
        "line": 42
      }
    }
  ]
}
```

## Operational Safety & Invariants
- **Sanitized Git Environment**: Runs with `GIT_CONFIG_NOSYSTEM=1` and `GIT_CONFIG_GLOBAL=/dev/null` to prevent configuration injection.
- **Sensitive Path Redaction**: Automatically suppresses credential files (`.env`, `id_rsa`, `*.pem`, `*.key`) from the diff payload.
- **Physical Line Verification**: Rejects any LLM finding whose referenced line or code excerpt does not physically exist in the target snapshot.
