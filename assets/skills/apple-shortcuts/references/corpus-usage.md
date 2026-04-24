# Corpus Usage

Use this reference to locate and query the local Shortcuts corpus.

## Corpus Root Resolution
The helper scripts resolve corpus root in this order:
1. `--corpus-root <path>` argument.
2. `APPLE_SHORTCUTS_CORPUS` environment variable.
3. Nearest `shortcuts-docs-corpus/` found from current directory upward.

Check detection quickly:
```bash
uv run --script <skill-dir>/scripts/cli.py search --query "sanity check" --top 1 --show-corpus-root
```

## Key Artifacts
- Expert text corpus: `shortcuts-docs-corpus/expert-pack/text/`
- RAG chunks: `shortcuts-docs-corpus/expert-pack/chunks/shortcuts_expert_chunks.jsonl`
- Source manifest: `shortcuts-docs-corpus/expert-pack/manifests/source_catalog.tsv`
- Download status: `shortcuts-docs-corpus/expert-pack/manifests/download_status.tsv`
- Coverage report: `shortcuts-docs-corpus/reports/coverage_report.md`

## Fast Search Patterns
- Search chunk JSONL with helper script:
```bash
uv run --script <skill-dir>/scripts/cli.py search \
  --query "run shortcuts from command line" --group support --top 10
```

- Search raw text quickly (if corpus root is known by env var):
```bash
rg -n "Ask for Input|x-callback-url|App Intents" \
  "$APPLE_SHORTCUTS_CORPUS/expert-pack/text"
```

- List official sources by category:
```bash
awk -F'\t' 'NR>1{print $2 "\t" $4}' \
  "$APPLE_SHORTCUTS_CORPUS/expert-pack/manifests/source_catalog.tsv" \
  | sort -u
```

## Source Group Semantics
- `support`: Apple Support user guides and topic pages.
- `developer`: Apple Developer docs and data JSON extraction.
- `wwdc`: WWDC session pages/transcripts.
- `community`: Non-Apple sources with quality risk.
- `cli`: Local `shortcuts` CLI docs and manpage.
