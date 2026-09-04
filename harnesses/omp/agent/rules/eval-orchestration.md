---
name: eval-orchestration
description: Prefer eval for in-memory data distillation, OLAP, and complex algorithms; never proxy specialized harness tools
condition:
  - '\b(eval|JSON|jsonl|session|transcript|analy[sz]e|aggregate|count|batch|parse|rank(?:ing)?|leaderboard|benchmark|telemetry|metrics?|triage|diagnostics?|polars|duckdb|rapidfuzz|networkx|AST|fuzzy|cluster|excel|xlsx|pdf|parquet|csv|rewrite config|filesystem|data munging|multi-step script|script)\b'
  - '\b(?:python|node|bun)\s+-[ce]\b|\bjq\b|\bawk\b|\bwhile\b|\bfor\s+\w+\s+in\b|<<[A-Za-z_]'
scope:
  - text
  - thinking
  - tool:bash
interruptMode: never
---
Always load `skill://python` when working with `eval`. Use `eval` strictly for in-memory data distillation, OLAP queries, complex algorithms, and dynamic `@tool` orchestration. Avoid heredocs, shell loops, inline interpreter one-liners, and quote-heavy Bash.

**Tool-First Boundary:** Never use `eval` as a proxy to circumvent specialized harness tools:
- Use `read` (with line selectors) to inspect code/text — avoid `Path.read_text()` or `open().read()`.
- Use `glob` / `grep` for discovery — avoid `os.walk()` or `re.search()` file loops.
- Use `bash` for toolchains, builds, tests, git, and CLIs — avoid `subprocess.run()`.
- Use `edit` / `write` for file mutations — avoid `open('w').write()`.

Proactively select the optimal tool over manual Python loops or raw text munging:

| Domain / Workload | Preferred Tool | Key Use Case |
|---|---|---|
| **Tabular Data & Log Metrics** | `polars` / `fastexcel` | Fast columnar filtering, group-by, aggregations, Excel `.xlsx` reads |
| **Direct File SQL / OLAP** | `duckdb` | Zero-copy SQL over Parquet, JSONL, CSV, SQLite files without memory bloat |
| **PDF & Document Extraction** | `pymupdf` | High-speed text/table extraction (`find_tables()`), layout & page rendering |
| **Fuzzy Matching & Search** | `rapidfuzz` | `process.extract()`, Levenshtein distance, typo tolerance, error clustering |
| **Dependency Graphs & Blast Radius** | `networkx` | Architectures, import/call graphs, cycle detection, shortest paths |
| **HTTP & API Fetching** | `httpx` | Async/sync REST requests and structured JSON payload retrieval |
| **Syntax, AST & Diffs** | `ast` / `difflib` | AST inspection/transforms, unified diffs, sequence matching (stdlib) |
| **Sequences & Buffers** | `itertools` / `collections` | Combinatorics, chunking, `Counter` histograms, `deque` buffers (stdlib) |

Distill, filter, and structure data inside `eval` first to maximize token density and eliminate context noise. Define `@tool` functions in `eval` to expose custom typed capabilities directly to subagents via `task(tools=[...])`.
