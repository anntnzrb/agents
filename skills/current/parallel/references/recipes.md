# Parallel Workflow Recipes

Note: Command and flag spellings in this document are illustrative and subject to CLI evolution. Always confirm exact options and syntax with `uvx --from "parallel-web-tools[cli]" parallel-cli <command> --help` before execution.

## Recipe 1: Fast web search and source extraction

### Objective
Answer a specific technical or factual question by retrieving relevant web pages and extracting full source content only when excerpts are insufficient.

### Steps
1. Inspect search options:
   Run `uvx --from "parallel-web-tools[cli]" parallel-cli search --help` to confirm available filters (such as mode, date cutoffs, domain inclusions, and output flags).
2. Execute focused search:
   Run short, specific queries covering distinct angles rather than one long, overloaded prompt. Request a small result count (for example 3 to 5 results). Save output to a file to keep context compact.
3. Review matches:
   Inspect titles, URLs, and excerpts in the saved output using jq or targeted reads.
4. Extract complete content:
   If an excerpt lacks necessary details (such as full code blocks or exact API signatures), extract full markdown only from the one or two most authoritative URLs. If the target page requires client-side JavaScript rendering and returns thin or empty markdown, use a rendering scraper.

### Illustrative commands
```bash
# Verify search options
uvx --from "parallel-web-tools[cli]" parallel-cli search --help

# Run fast search with a tight result set and save to disk
uvx --from "parallel-web-tools[cli]" parallel-cli search "<focused query>" \
  --mode fast \
  --max-results 3 \
  -o <temp-dir>/search_results.json

# Inspect results cleanly without dumping large blobs
jq -r '.results[] | "\(.title)\n\(.url)\n"' <temp-dir>/search_results.json

# Extract full page content only for the top authoritative URL
uvx --from "parallel-web-tools[cli]" parallel-cli extract "<top-url>" \
  --full-content \
  -o <temp-dir>/extracted_doc.json
```

## Recipe 2: Deep research with cost awareness

### Objective
Synthesize an open-ended technical or industry question into a comprehensive report with inline citations while selecting the most economical processor tier.

### Steps
1. Check processor tiers:
   Run `uvx --from "parallel-web-tools[cli]" parallel-cli research processors` to review available tiers, execution times, and depth trade-offs.
2. Select the right tier:
   Choose the lowest tier suited to the task. Use fast or lite tiers for quick lookups and moderate research; reserve higher tiers for difficult multi-source synthesis.
3. Launch research task:
   Execute research specifying the chosen processor, markdown text output format, and an output path. The CLI manages polling and saves the report to disk upon completion.
4. Review output:
   Read the resulting markdown report file from disk.

### Illustrative commands
```bash
# List available processor tiers
uvx --from "parallel-web-tools[cli]" parallel-cli research processors

# Run research with a lightweight processor and save markdown report to disk
uvx --from "parallel-web-tools[cli]" parallel-cli research run \
  "<research question>" \
  --processor <cheapest-fitting-tier> \
  --text \
  -o <temp-dir>/ci_package_comparison

# Inspect generated report
cat <temp-dir>/ci_package_comparison.md
```

## Recipe 3: Entity discovery and enrichment

### Objective
Discover a structured list of entities matching descriptive natural language criteria and enrich them with specific data points.

### Steps
1. Check findall and enrich options:
   Run `uvx --from "parallel-web-tools[cli]" parallel-cli findall --help` and `uvx --from "parallel-web-tools[cli]" parallel-cli enrich --help`.
2. Discover entities:
   Run FindAll with an objective describing target entities (such as companies or software tools) and desired criteria.
3. Poll to completion:
   If running asynchronously, use the CLI poll command to wait for the run to complete and write results to disk.
4. Enrich entity data:
   Run enrichment against the discovered entities to fetch supplementary attributes.

### Illustrative commands
```bash
# Discover entities matching criteria
uvx --from "parallel-web-tools[cli]" parallel-cli findall run \
  "<entity criteria>"

# Check status or poll run to completion
uvx --from "parallel-web-tools[cli]" parallel-cli findall poll <run_id> -o <temp-dir>/entities.json

# Enrich results with targeted attributes
uvx --from "parallel-web-tools[cli]" parallel-cli enrich run \
  --input <temp-dir>/entities.json \
  -o <temp-dir>/enriched_entities.json
```

## Recipe 4: Semantic topic monitoring

### Objective
Track a dynamic web topic, product category, or documentation site for changes over time.

### Steps
1. Inspect monitor options:
   Run `uvx --from "parallel-web-tools[cli]" parallel-cli monitor --help`.
2. Create monitor:
   Define the target topic, query, or site to watch along with the polling cadence.
3. Check events:
   List new events detected by the monitor and inspect individual event diffs.

### Illustrative commands
```bash
# Verify monitor creation options
uvx --from "parallel-web-tools[cli]" parallel-cli monitor create --help

# Create topic monitor
uvx --from "parallel-web-tools[cli]" parallel-cli monitor create \
  --query "<topic to watch>"

# List detected events
uvx --from "parallel-web-tools[cli]" parallel-cli monitor events <monitor_id>
```

## Recipe 5: Recalling past research from memory

### Objective
Check saved interactions, tasks, or monitor events before launching duplicate queries.

### Steps
1. Inspect memory commands:
   Run `uvx --from "parallel-web-tools[cli]" parallel-cli memory --help`.
2. Search memory:
   Run memory query with relevant keywords to locate past task outputs or findings.
3. Continue research:
   When refining an earlier investigation, pass the previous interaction ID to research run to maintain context.

### Illustrative commands
```bash
# Search memory for earlier work
uvx --from "parallel-web-tools[cli]" parallel-cli memory "<keywords>"

# Continue research using context from earlier interaction
uvx --from "parallel-web-tools[cli]" parallel-cli research run \
  "<follow-up question>" \
  --previous-interaction-id <interaction_id> \
  --processor <cheapest-fitting-tier> \
  --text \
  -o <temp-dir>/follow_up_benchmark
```
