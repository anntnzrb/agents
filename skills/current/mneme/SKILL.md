---
name: mneme
description: "Use when denoising meeting transcripts, extracting action items, or searching audio notes, not for coding sessions."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Mneme

Use this skill when processing conversational transcripts, denoising audio notes, writing meeting minutes and action items, or querying historical meeting context.

## Overview

Mneme handles meetings in three phases:

1. **Lossless denoising**: `denoise` strips fillers, stutter loops, and false starts and rebuilds speaker turns. The agent then fixes speaker identities and anything the script missed, and `verify` checks that no number was lost.
2. **Minutes**: the agent writes the minutes and action items itself, grounded in the roster and in the archive's existing format. No script does this step.
3. **Retrieval**: search and fetch exact dialogue across indexed transcripts with local hybrid search.

## Public entrypoint

```bash
uv run --script skills/current/mneme/scripts/cli.py <command> [options]
```

## Required follow-up reads

| Need | Read | When |
| :--- | :--- | :--- |
| Lossless transcript cleaning rules | `references/lossless-cleaning.md` | Denoising raw transcripts without dropping information |
| Minutes layout, grounding, and Linear archive | `references/spec-synthesis.md` | Writing minutes or action items, or archiving a meeting |
| Search engine integration reference | `references/qmd-integration.md` | Searching, indexing, or querying meeting archives |

## Common calls

### 1. Denoise a raw transcript losslessly
```bash
uv run --script skills/current/mneme/scripts/cli.py denoise raw_transcript.md -o clean_transcript.md
```

### 2. Check that cleaning kept every number
```bash
uv run --script skills/current/mneme/scripts/cli.py verify raw_transcript.md clean_transcript.md
```
Exit `1` lists each number missing from the clean file. Run it after every manual edit too.

### 3. Hybrid search over indexed meeting knowledge base
```bash
uv run --script skills/current/mneme/scripts/cli.py search "quarterly budget timeline" --json
```

### 4. Search exact terms via keyword search
```bash
uv run --script skills/current/mneme/scripts/cli.py search "Project Delta" --exact
```

### 5. Fetch a line-ranged transcript snippet
```bash
uv run --script skills/current/mneme/scripts/cli.py get "#<docid>:<line>:<count>"
```

## Core Rules

- **Lossless Invariance**: When cleaning transcripts, NEVER summarize, drop, or condense dialogue, metrics, dates, or tangents. Only remove verbal tics, stutter loops, and false starts.
- **Strict Diarization**: Preserve every speaker change in chronological sequence. NEVER merge alternating dialogue turns into a single speaker block or insert artificial topic headings into a transcript.
- **Speaker Identity**: Map generic labels such as `Speaker 4` to roster names from context, and confirm the mapping with the user when it is uncertain. Drop a label with only stray crosstalk fragments only when the user confirms it is noise.
- **Archive First**: Before writing minutes, read the archive's index, roster, and one recent minutes document, and match their language and layout.
- **Grounded Minutes**: Use full roster names. Ask for the date and time when the transcript lacks them. Omit ambiguous figures from the minutes instead of guessing; the transcript keeps them verbatim.
- **Targeted Retrieval**: Fetch exact line-ranged snippets (`#<docid>:<line>:<count>`) instead of reading whole transcript files into the context window.
