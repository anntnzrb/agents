---
name: research
description: Route research, fact-checking, comparisons, and evidence gathering to the best available source.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Research Router

Route research requests to the right source class, then return source-backed answers with confidence and gaps.

## Routing policy

- Prefer active tools for common search, URL retrieval, repository inspection, and browsing.
- Use a specialized skill when its source or behavior matches the request better.
- Prefer live data for open-web questions.
- Pick the smallest route set that can answer the question.
- If evidence is thin, add a second source class for corroboration.
- Keep source provenance explicit in final output.

## Route map

### Code/docs research

- Use available GitHub or repository tools, or `gh`, for repository inspection and code search.
- Use `deepwiki` for repository docs/Q&A over `owner/repo`.
- Use `context7` for current library/API docs and examples.
- Use `grep-app` for public OSS code usage patterns.

### Web/live research

- Use built-in web search for ordinary live discovery.
- Use `omp-search` when the OMP CLI's automatic provider chain, explicit provider selection, or structured headless output is useful.
- Use URL retrieval tool for known static pages; use its browser tool only for interaction, authentication, or JavaScript-rendered pages.
- Use `brave-search` for direct Brave-backed scoping and recency checks.
- Do not run multiple routes that merely duplicate the same provider and evidence.

### Sentiment/discussion research

- Use `reddit` for community sentiment, discussion trends, and user/topic signals.
- Corroborate high-impact claims with one non-Reddit source class when feasible.

### X/Twitter research

- Use `x-research` for explicit X/Twitter post URLs or IDs, bounded timelines, post search, and conversations.
- For X-plus-web news work, use `x-research` for bounded X evidence, then an independent web route.
- Treat X results as bounded, unofficial evidence; never infer public-opinion truth, deletion, or suspension from a missing result.

### Knowledge-base research

- Use `notebooklm` for user-owned notebook sources and internal knowledge corpora.

### Exclusions

- Do not substitute generic summarization for evidence retrieval.

## Router workflow

1. Classify the request: code/docs, web/live, sentiment, X/Twitter, or notebook KB.
2. Start with active route for common operations.
3. Select a specialized skill when the route map gives it a better source or behavior match.
4. Execute the route and collect source evidence.
5. Add a different source class when confidence is low, sources conflict, or claim impact is high.
6. Return the answer with provenance, confidence, and explicit gaps.

## Output contract

- Answer: concise result.
- Sources used: route + why it was selected.
- Confidence: high/medium/low with reason.
- Gaps: unresolved uncertainty or missing evidence.
- Next query: best follow-up when blocked.

## Escalation rules

- If library/API details are unclear, use `context7`; fall back to official docs.
- If repository behavior is unclear, use repository inspection plus `deepwiki` when useful.
- If web evidence is stale or shallow, try another search provider; use `omp-search` when its provider chain is available.
- If a sentiment claim drives decisions, include `reddit` plus one non-Reddit source.
