# Firecrawl Research Index Reference

Access Firecrawl's research paper corpus spanning biomedical and life-sciences literature (PubMed, bioRxiv, medRxiv) alongside arXiv preprints (CS, physics, math).

## Subcommands

1. `firecrawl research search-papers <query>`: Semantic (HyDE) search over paper abstracts.
2. `firecrawl research related-papers <seedIds...>`: Semantic and citation-graph expansion.
3. `firecrawl research inspect-paper <id>`: Canonical metadata for a single paper.
4. `firecrawl research read-paper <id> --question <question>`: In-body passage search within full text.

## Options & Flags

- `--k <number>`: Number of candidates to return.
- `--intent <intent>`: Goal description for ranking related papers.
- `--mode <mode>`: Expansion mode:
  - `similar`: Topical and methodology neighbors.
  - `citers`: Papers that build on or cite the seed papers.
  - `references`: Foundational papers that the seeds build upon.
- `--question <question>`: Specific factual query for in-body paper verification.
- `-o, --output <path>`: Write results to file.
- `--json`: Format output as JSON.

## Workflow Patterns

### 1. Initial Abstract Discovery
```bash
firecrawl research search-papers "CRISPR off-target cleavage prediction transformers" --k 10 --json -o .firecrawl/crispr.json
```

### 2. Citation Graph & Method Family Expansion
```bash
# Expand from seed paper IDs to find competing methods and citing research
firecrawl research related-papers "pubmed:38123456" "arxiv:2401.09876" \
  --intent "Find transformer-based off-target prediction benchmarks" \
  --mode similar --k 10 --json -o .firecrawl/related.json
```

### 3. Canonical Metadata Inspection
```bash
firecrawl research inspect-paper "arxiv:2401.09876" --json -o .firecrawl/metadata.json
```

### 4. In-Body Fact Verification
```bash
# Verify specific benchmark score or experimental parameter inside the paper body
firecrawl research read-paper "arxiv:2401.09876" \
  --question "What was the reported AUROC score on the GUIDE-seq benchmark?" \
  --json -o .firecrawl/paper-facts.json
```

## Critical Distinctions

- `firecrawl research` searches the 43M+ abstract corpus with citation graphs and full-text indexing.
- `firecrawl search --categories research` is an open web search filtered to research domain URLs; it does not access paper citation graphs or in-body passage verification.
