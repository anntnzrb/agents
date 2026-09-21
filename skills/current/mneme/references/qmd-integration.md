# Search & Retrieval Integration Reference

This reference documents how to interact with the local transcript knowledge base via the unified Mneme CLI search command and the underlying `qmd` retrieval engine.


## Unified Search Command

Mneme provides a single polymorphic `search` entrypoint modeled after modern retrieval systems:

```bash
uv run --script skills/current/mneme/scripts/cli.py search <query> [options]
```

### 1. Hybrid Search (Default)
By default, `search` executes a hybrid search combining BM25 keyword matching, dense vector embeddings, and an LLM reranker (via `qmd query`). This is best for natural language questions, conceptual queries, and conversational context:

```bash
uv run --script skills/current/mneme/scripts/cli.py search "what was the agreed timeline for project kickoff"
```

Structured typed queries can also be passed directly to target lexical and vector components:
```bash
uv run --script skills/current/mneme/scripts/cli.py search $'lex: "budget review" timeline\nvec: when will the next phase start'
```

### 2. Exact Keyword Search (`--exact`)
Passing `--exact` switches from hybrid retrieval to pure BM25 lexical keyword matching (via `qmd search`). This is best for exact terms, names, dates, amounts, or project identifiers:

```bash
uv run --script skills/current/mneme/scripts/cli.py search "Project Delta" --exact
uv run --script skills/current/mneme/scripts/cli.py search "Q3-Budget" --exact -c meetings
```

### 3. Disabling Reranker (`--no-rerank`)
For faster hybrid queries where LLM reranking latency is unnecessary:

```bash
uv run --script skills/current/mneme/scripts/cli.py search "quarterly budget timeline" --no-rerank
```

### 4. Limiting and Scoping
- `-c, --collection <name>`: Target a specific collection (default: auto).
- `-n, --limit <count>`: Number of results to return (default: 5).

```bash
uv run --script skills/current/mneme/scripts/cli.py search "battery life" -c meetings -n 10
```

---

## JSON Output Contract (`--json`)

Passing `--json` instructs the search command to return machine-readable structured JSON containing rich snippets, document IDs, line numbers, and relevance scores:

```bash
uv run --script skills/current/mneme/scripts/cli.py search "battery issues" --json
```

### Response Schema

```json
[
  {
    "docid": "#abc1234",
    "file": "transcripts/clean_ES2004b.md",
    "title": "Clean Transcript: ES2004b",
    "score": 0.892,
    "line": 42,
    "snippet": "Industrial Designer: On battery issue, we want to minimize the size of the battery. Meanwhile, cost, power consumption, wireless range and data transmission were supposed to be considered."
  }
]
```

### Contract Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `docid` | string | Unique document identifier in the index (includes leading `#`) |
| `file` | string | Relative or display path to the transcript file in the index |
| `title` | string | Document title or heading |
| `score` | float | Relevance / reranking score |
| `line` | integer (optional) | Starting line number of the matching passage |
| `context` | string (optional) | Surrounding context header if available |
| `snippet` | string | Verbatim transcript dialogue text surrounding the match |

Agents can parse the returned JSON directly to answer user queries from the matched snippets without making an additional read call.

---

## Line-Targeted Retrieval (`get`)

When deeper context surrounding a matched `#docid` is needed, use the `get` command to fetch specific line ranges rather than loading entire transcript files into the context window:

```bash
# Fetch 15 lines starting from line 40 of document #abc1234
uv run --script skills/current/mneme/scripts/cli.py get "#abc1234:40:15"
```

---

## Index and Collection Management (`qmd`)

When new clean transcripts are saved to disk, update the index using `qmd` directly:

```bash
# Add folder to collection if not already added
qmd collection add ~/vault/meetings --name meetings

# Attach semantic folder context
qmd context add qmd://meetings "Transcripts and notes from team meetings and discussions"

# Update index and refresh embeddings
qmd update
qmd embed
```

---

## Running as MCP Server

For persistent agent connections:

```bash
# Start background HTTP MCP daemon on port 8181
qmd mcp --http --daemon

# Check daemon status
qmd status

# Stop daemon
qmd mcp stop
```
