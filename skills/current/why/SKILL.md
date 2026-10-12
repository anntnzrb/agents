---
name: why
description: "Use when investigating why code was written a certain way via git blame, PRs, or issues, not for how it works today."
license: AGPL-3.0-or-later
---

# Why

Investigate the motivation and intent behind code. The companion `how` skill explains what the code does and how it works. `why` explains what forces led to its shape.

Adapted from pstack (Lauren Tan, MIT): MCP discovery replaced with the sources actually available here: git, `gh`, and repo-local documents.

## Operating posture

Investigate precisely. When the record is thin, say so.

Classify each claim as **Direct** (an author states the reason), **Supported** (several indirect records converge), **Inferred** (your interpretation), **Speculative** (one of several plausible explanations), or **Unknown** (searched without an answer). Match the phrasing to the tier and cite the records behind it.

- **Evidence before narrative.** Collect the pieces first, then see what story they support. Never pick a story and recruit the evidence that fits it.
- **Cite everything.** Every claim about intent references a commit hash, PR number, issue id, doc path, or code comment with `file:line`. If you can't cite it, it is inference and gets labeled as such.
- **Prefer "appears to" over "because".** Hedge when evidence is indirect. Confidence-matching phrasing is a feature of the output, not a stylistic choice.
- **Surface contradictions.** If two sources disagree, show both. Don't quietly pick the one that fits.
- **Name the gaps.** If a thread goes cold or a source is not searchable, document the gap. An honest "we couldn't find out why" beats a confident guess.
- **Multiple hypotheses are valid.** When the evidence fits several stories, present them all with evidence for each. Let the user triangulate.
- **Beware rationalization.** Code that makes sense today may have been written for reasons that no longer apply. Don't retrofit intent.
- **No shortcut by code-reading.** The code tells you what it does, rarely why it exists. Resist inferring intent from code shape.

## Step 1. Understand the target and the question

The **target** is a chunk of code, a pattern, a feature, or a named design decision. The **question** is usually a design rationale, a tradeoff, a motivating edge case, an external constraint, dead code, or a broad history.

If the target is vague, make your best guess from conversation context, state your interpretation briefly so the user can redirect, then proceed.

## Step 2. Establish the code anchor

Anchor the investigation in concrete code before spawning investigators:

```bash
git blame -L <start>,<end> <file>
git log --follow -p -- <file>
git log --oneline -20 -- <file>
git log -1 --format=%B <commit>
gh pr view <number> --json title,body,author,createdAt,mergedAt,labels,closingIssuesReferences,comments,reviews
```

Capture file paths and line ranges, symbols, commits, PR numbers, and linked issue ids. Give this context to every investigator and use it during synthesis.

## Step 3. Spawn parallel investigators

Launch all matching investigators concurrently as read-only subagents when the harness supports them; otherwise run the investigations sequentially yourself. Assign one investigator per source.

Available sources in this environment:

1. **Source control.** Git history plus `gh` for PRs. Always spawn; the only guaranteed source. Best at implementation-time rationale: PR descriptions stating the problem, review threads debating alternatives, inline comments encoding constraints, commit messages linking issues.
2. **Issues and PRs.** `gh` issue and PR search over the repo. Best at the product or business forcing function: customer requests, compliance deadlines, initiative framing, labels that categorize motivation.
3. **Repo-local documents.** ADRs, RFCs, specs, READMEs, design docs, postmortems found in the tree and their git history. Best at long-form design rationale: problem statements, "alternatives considered" sections, finalized decisions.
4. **Web research.** Only when the repo references an external source (a linked doc, an incident report, a public discussion) or the user asks. Use the repo's research tooling.

Sources with no available tooling (team chat, infra observability, error tracking, analytics warehouse) are recorded as gaps in Sources Consulted, never silently skipped. A null result from a searched source is a finding; a skipped search is a blind spot.

Give each investigator the code anchor, the user's question, and its source's queries. For `gh`, use issue search, PR views, and API reads. For git, use blame, log with `--follow`, and `-S` pickaxe search. For documents, find files with `rg --files`, read them, and follow their history.

Each investigator reads complete records, follows links within its own source, and records cross-source leads for the owning investigator. Return exact quotes or accurate paraphrases with citations, contradictions, and the queries that found nothing. Keep findings separate from conclusions. For defensive code, search for incidents using exception names, error strings, symbols, and the dates around the change.

## Step 4. Synthesize

Weigh the findings, merge duplicate citations, and preserve contradictions. Spot-check citations against the original records. Verify an uncertain citation before using it. Keep this step read-only.

## Output format

Adapt as needed, but keep the confidence separation intact.

**The Question.** Restate what the user asked, concisely.

**The Code in Question.** File paths, line ranges, and key symbols.

**What We Found.** Label claims as Direct or Supported. Cite each source (PR #, issue id, commit hash, doc path, or code comment with `file:line`). A Direct claim quotes or paraphrases an explicit rationale. A Supported claim names the converging records without claiming an author stated the reason.

**What We Can Reasonably Infer.** Claims supported by indirect evidence or signal combinations. Each bullet explains the inference chain: "Given A and B, it's likely that C." Hedged language.

**Competing Hypotheses.** If the evidence fits multiple stories, list each with evidence for and against. Skip if there is a clear answer.

**What We Don't Know.** Explicit gaps: unanswered questions, sources that came up empty. Be specific.

**Sources Consulted.** One line per source: what was searched, what was found or "no relevant results", or "unavailable. gap".

End with a brief confidence summary separating the established rationale from inferred details and unanswered questions.

Example lines:

- Source control (git/gh): `git log --follow backend/retry.ts`, PRs #49074, #47812. Found PR #49074 introduced exponential backoff and linked ENG-4421.
- Issues (gh): searched "retry" and ENG-4421. Found ENG-4421 parent issue but no discussion of backoff parameters.
- Repo-local docs: searched "retry policy", "backoff". No relevant results.
- Team chat: unavailable. No tooling in this environment. Gap: conversational record not searched.

If the `why` question is a precursor to changing this code, close with a Preserve / Change / Avoid / Risk constraint set for planning the change.

## Common failure modes

- **Confident storytelling.** A plausible narrative built from thin evidence. A bullet with no citation goes in inferred or hypotheses, not found.
- **Citing the code as evidence for its own intent.** "Handles the null case because it checks for null" is mechanics, not motivation.
- **Recency bias.** The current shape is often the accretion of many earlier decisions. Trace back.
- **Sycophantic agreement.** If the user suggests a reason, treat it as a hypothesis and check the evidence independently.
- **Skipping the gaps section.** An honest accounting of what you couldn't find out is part of the value.
