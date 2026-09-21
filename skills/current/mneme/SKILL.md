---
name: mneme
description: "Use when processing meeting transcripts, audio notes, synthesizing action items/summaries, or querying notes."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Mneme

Use this skill when processing conversational transcripts, denoising audio notes, synthesizing action items and summaries from discussions, or querying historical meeting context.

## Overview

Mneme structures meeting and conversational intelligence into three distinct phases:

1. **Lossless Denoising (Zero Information Loss)**: Clean raw ASR audio transcripts, eliminate speech recognition loops and verbal tics, and reconstruct accurate speaker turns without summarizing or dropping facts, numbers, dates, decisions, or tangents.
2. **Synthesis and Action Extraction**: Generate structured executive summaries, key decisions, and actionable task items (with clear context, scope, and completion criteria) suitable for any task management system or personal checklist.
3. **Contextual Retrieval (Talk with your notes)**: Search and retrieve exact historical dialogue and agreements across indexed notes using local hybrid search.

## Public entrypoint

```bash
uv run --script skills/current/mneme/scripts/cli.py <command> [options]
```

## Required follow-up reads

| Need | Read | When |
| :--- | :--- | :--- |
| Lossless transcript cleaning rules | `references/lossless-cleaning.md` | Denoising raw transcripts without dropping information |
| Action item & summary schemas | `references/spec-synthesis.md` | Converting conversations into structured tasks and summaries |
| Search engine integration reference | `references/qmd-integration.md` | Searching, indexing, or querying meeting archives |

## Common calls

### 1. Denoise a raw transcript losslessly
```bash
uv run --script skills/current/mneme/scripts/cli.py denoise raw_transcript.md -o clean_transcript.md
```

### 2. Synthesize summary and actionable tasks
```bash
uv run --script skills/current/mneme/scripts/cli.py synthesize clean_transcript.md --summary summary.md --tasks tasks.json
```

### 3. Hybrid search over indexed meeting knowledge base
```bash
uv run --script skills/current/mneme/scripts/cli.py search "quarterly budget timeline"
```

### 4. Search exact terms via keyword search
```bash
uv run --script skills/current/mneme/scripts/cli.py search "Project Delta" --exact
```
## Core Rules

- **Lossless Invariance**: When cleaning transcripts, NEVER summarize, drop, or condense dialogue, metrics, dates, or tangents. Only remove verbal tics, stutter loops, and correct speaker labels.
- **Actionable Synthesis**: Convert conversational agreements into unambiguous task items with clear owners, concrete scope, and explicit completion criteria.
- **Targeted Retrieval**: Fetch exact line-ranged snippets (`#docid:line:count`) instead of reading whole transcript files into the context window.
