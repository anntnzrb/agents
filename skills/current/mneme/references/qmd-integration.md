# Search & Retrieval Integration Reference



## Section index


# Fetch 15 lines starting from line 40 of document #abc1234
uv run --script <skill-dir>/scripts/cli.py get "#abc1234:40:15"
```

---

## Index and Collection Management (`qmd`)

When new clean transcripts are saved to disk, update the index using `qmd` directly:

```bash
# Add folder to collection if not already added
qmd collection add <meetings-dir> --name meetings

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
