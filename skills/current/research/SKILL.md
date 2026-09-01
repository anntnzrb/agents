---
disable-model-invocation: true
name: research
description: "Use when a task requires research, fact-checking, comparison, evidence gathering, or source selection."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Research Router

Route each request to the right source class; return a source-backed answer with explicit provenance, confidence, and gaps.

## Routing policy

- Prefer active tools for common search, URL retrieval, repository inspection, and browsing.
- Use a specialized skill when its source or behavior better matches the request.
- Open-web questions: prefer live data.
- Choose the smallest route set sufficient to answer.
- Thin evidence: add a second source class for corroboration.
- Do not run multiple routes duplicating a provider and its evidence.

## Route map

### Code/docs

- Repository inspection/code search: available GitHub or repository tools, or `gh`.
- Repository docs/Q&A over `owner/repo`: `deepwiki`.
- Current library/API docs and examples: `context7`.
- Public OSS usage patterns: `grep-app`.

### Web/live

- Ordinary live discovery: built-in web search.
- Use `omp-search` when its OMP CLI automatic provider chain, explicit provider selection, or structured headless output is useful.
- Known static pages: URL retrieval tool; browser tool only for interaction, authentication, or JavaScript-rendered pages.
- Direct Brave-backed scoping and recency checks: `brave-search`.

### Sentiment/discussion

- Community sentiment, discussion trends, and user/topic signals: `reddit`.
- When feasible, corroborate high-impact claims with one non-Reddit source class.

### X/Twitter

- Explicit X/Twitter post URLs or IDs, bounded timelines, post search, and conversations: `x-research`.
- X-plus-web news: use `x-research` for bounded X evidence, then an independent web route.
- X results are bounded, unofficial evidence; never infer public-opinion truth, deletion, or suspension from a missing result.

### Knowledge base

- User-owned notebook sources and internal knowledge corpora: `notebooklm`.

## Exclusion

- Do not substitute generic summarization for evidence retrieval.

## Workflow

1. Classify the request: code/docs, web/live, sentiment, X/Twitter, or notebook KB.
2. Start with the active route for common operations.
3. Select a specialized skill when the route map gives it a better source or behavior match.
4. Execute the route and collect source evidence.
5. Add a different source class when confidence is low, sources conflict, or claim impact is high.
6. Return the answer with provenance, confidence, and explicit gaps.

## Output contract

- Answer: concise result.
- Sources used: route and why selected.
- Confidence: high, medium, or low, with reason.
- Gaps: unresolved uncertainty or missing evidence.
- Next query: best follow-up when blocked.

## Escalation rules

- Unclear library/API details: use `context7`; fall back to official docs.
- Unclear repository behavior: use repository inspection plus `deepwiki` when useful.
- Stale or shallow web evidence: try another search provider; use `omp-search` when its provider chain is available.
- Decision-driving sentiment claim: include `reddit` plus one non-Reddit source.
