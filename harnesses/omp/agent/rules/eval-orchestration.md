---
name: eval-orchestration
description: Prefer eval for in-memory data distillation, OLAP, and complex algorithms; never proxy specialized harness tools
condition:
  - '\b(?:python|node|bun)\s+-[ce]\b|\bjq\b|\bawk\b|\bwhile\s+(?:true\b|read\b|\[|:|getopts\b)|\bfor\s+\w+\s+in\s|<<[A-Za-z_]'
  - '\b(?:subprocess\.(?:run|Popen|check_output|check_call)|os\.(?:system|popen|walk))\b|\.(?:read_text|write_text)\(|open\([^)\n]{0,40}[''"]'
scope:
  - tool:eval
  - tool:bash
interruptMode: never
---
Always load `skill://python` when working with `eval`. Use `eval` strictly for in-memory data distillation, OLAP queries, complex algorithms, and dynamic `@tool` orchestration. Avoid heredocs, shell loops, inline interpreter one-liners, and quote-heavy Bash.

**Tool-First Boundary:** Never use `eval` as a proxy to circumvent specialized harness tools:
- Use `read` with line selectors to inspect code or text, not `Path.read_text()` or `open().read()`.
- Use `glob` and `grep` for discovery, not filesystem walks or regex file loops inside `eval`.
- Use `bash` for toolchains, builds, tests, git, and CLIs, not `subprocess.run()` inside `eval`.
- Use `edit` and `write` for file mutations, not Python file writes.

Choose libraries for the analysis, not as substitutes for specialized tools. The table does not authorize HTTP fetching, document inspection, or filesystem discovery inside `eval`. Prefer `read` for supported document and database queries; use analytical engines only when the requested computation needs them.

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
