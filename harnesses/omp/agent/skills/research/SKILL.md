---
name: research
description: Research router for selecting the best source path across repository docs, API/library docs, OSS code patterns, live web search, and Reddit sentiment. Use when tasks involve research, fact-checking, source-backed comparisons, evidence gathering, trend checks, or confidence validation. Route code/docs work to deepwiki+context7+grep-app, route web/live work to brave-search+exa-search, route sentiment/discussion to reddit. Exclude summarize from this router.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Research Router

Route research requests to the right source class, then return source-backed answers. Search across independent source classes concurrently when the question spans domains.

## Routing policy

- Prefer live data for open-web questions.
- Pick the smallest route set that can answer the question.
- If evidence is thin, add a second source class for corroboration.
- Keep source provenance explicit in final output.

## Route map

### Code/docs research

- Use `deepwiki` for repository docs/Q&A over `owner/repo`.
- Use `context7` for up-to-date library/API docs and examples.
- Use `grep-app` for public OSS code usage patterns.
- Inspect repositories, issues, and pull requests directly when structure matters more than documentation.

### Web/live research

- Use `brave-search` for fast scoping, recency checks, images/video, and quick lookups.
- Use `exa-search` for deeper multi-source synthesis, full-page content, and richer retrieval.
- Escalate from Brave to Exa when coverage or quality is weak.

### Sentiment/discussion research

- Use `reddit` for community sentiment, discussion trends, and user/topic signals.
- Corroborate high-impact claims with one non-Reddit source class when feasible.

### Interactive research

- Use `agent-browser` for sites requiring login, JavaScript execution, or interactive navigation.
- Fall back to static reads when the page is plain text, docs, JSON, or a PDF.

### Exclusions

- Do not route to `summarize` from this skill.

## Router workflow

1. Classify request: code/docs, web/live, sentiment, or interactive.
2. Select primary route from the map above.
3. Search sources and collect evidence.
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
- If repo-specific behavior is unclear, force `deepwiki` and consult the repository directly.
- If web evidence is stale or shallow, escalate from `brave-search` to `exa-search`.
- If sentiment claim drives decisions, include `reddit` plus one non-Reddit corroboration source.
