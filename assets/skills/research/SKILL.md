---
name: research
description: Route research, fact-checking, comparisons, and evidence gathering to the best available source.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Research Router

Route research requests to the right source class, then return source-backed answers with confidence and gaps.

## Routing policy

- Prefer live data for open-web questions.
- Pick the smallest route set that can answer the question.
- If evidence is thin, add a second source class for corroboration.
- Keep source provenance explicit in final output.

## Route map

### Code/docs research

- Use `gh` for GitHub repository inspection and code search.
- Use `deepwiki` for repository docs/Q&A over `owner/repo`.
- Use `context7` for up-to-date library/API docs and examples.
- Use `grep-app` for public OSS code usage patterns.

`context7` uses the official read-only `ctx7` CLI for library docs. `grep-app` is direct HTTP. `deepwiki` may still be MCP-backed until its direct equivalent reaches Q&A parity.

### Web/live research

- Prefer OMP built-ins first: use `web_search` for discovery and `browser` only for interactive or JavaScript-rendered pages.
- Use `read` to retrieve a known static URL; it is a general retrieval tool, not a dedicated web-search route.
- Use `brave-search` for fast scoping and recency checks when the built-ins are insufficient.

`brave-search` is a direct HTTP skill.

### Sentiment/discussion research

- Use `reddit` for community sentiment, discussion trends, and user/topic signals.
- Corroborate high-impact claims with one non-Reddit source class when feasible.

`reddit` is direct HTTP via Reddit JSON endpoints.

### X/Twitter research

- Use `x-research` for explicit X/Twitter post URLs or IDs, bounded user timelines, post search, and conversations.
- For X-plus-web news work, use `x-research` for bounded X discovery/evidence, then `web_search` and `read` for independent sources.
- Treat X results as bounded, unofficial evidence; never infer public-opinion truth, deletion, or suspension from a missing result.

### Knowledge-base research

- Use `notebooklm` for user-owned notebook sources and internal knowledge corpora.

### Exclusions

- Do not route to `summarize` from this skill.

## Router workflow

1. Classify request: code/docs, web/live, sentiment, or notebook KB.
2. Select the primary route from the map above; for web/live work, start with the applicable OMP built-in.
3. Execute route tools and collect source evidence.
4. Add corroboration route when confidence is low, sources conflict, or claim impact is high.
5. Return answer with provenance, confidence, and explicit gaps.

## Output contract

- Answer: concise result.
- Sources used: tool + why it was selected.
- Confidence: high/medium/low with reason.
- Gaps: unresolved uncertainty or missing evidence.
- Next query: best follow-up when blocked.

## Escalation rules

- If library/API details are unclear, force `context7`.
- If repo-specific behavior is unclear, force `deepwiki` and/or `gh`.
- If web evidence is stale or shallow, use the available `brave-search` provider skill as a secondary route.
- If sentiment claim drives decisions, include `reddit` plus one non-Reddit corroboration source.
