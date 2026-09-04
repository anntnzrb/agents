---
name: eval-orchestration
description: Prefer eval for scripts, parsing, JSON, transcripts, and batch analysis
condition:
  - '\b(JSON|jsonl|session|transcript|analy[sz]e|aggregate|count|batch|parse|rewrite config|filesystem|data munging|multi-step script|script)\b'
  - '\b(?:python|node|bun)\s+-[ce]\b|\bjq\b|\bawk\b|\bwhile\b|\bfor\s+\w+\s+in\b|<<[A-Za-z_]'
scope:
  - text
  - thinking
  - tool:bash
interruptMode: never
---
Always load `skill://python` when working with `eval`. Use `eval` for orchestration, telemetry, batch filesystem ops, config rewrites, and multi-step tasks. Avoid heredocs, shell loops, inline interpreter one-liners, and quote-heavy Bash.

Proactively select the optimal tool over manual Python loops or raw text munging:

| Domain / Workload | Preferred Tool | Key Use Case |
|---|---|---|
| **Tabular Data & Log Metrics** | `polars` | Fast columnar filtering, group-by, aggregations, Excel reads (`fastexcel`) |
| **Direct File SQL / OLAP** | `duckdb` | Zero-copy SQL over Parquet, JSONL, CSV, SQLite files without memory bloat |
| **Fuzzy Matching & Search** | `rapidfuzz` | `process.extract()`, Levenshtein distance, typo tolerance, error clustering |
| **Dependency Graphs & Blast Radius** | `networkx` | Architectures, import/call graphs, cycle detection, shortest paths |
| **HTTP & API Fetching** | `httpx` | Async/sync REST requests and structured JSON payload retrieval |
| **Syntax, AST & Diffs** | `ast` / `difflib` | AST inspection/transforms, unified diffs, sequence matching (stdlib) |
| **Sequences & Buffers** | `itertools` / `collections` | Combinatorics, chunking, `Counter` histograms, `deque` buffers (stdlib) |

Distill, filter, and structure data inside `eval` first to maximize token density and eliminate context noise.
