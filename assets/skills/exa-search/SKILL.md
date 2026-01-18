---
name: exa-search
description: Deep web research, structured answers, and content retrieval using Exa. Use for heavy research, multi-step synthesis, or rich structured outputs; optionally pair with brave-search for fast scoping but not required.
---

# Exa Search

Use Exa for deep search, content retrieval, and research tasks. Requires `EXA_API_KEY`.

## Setup

Assume `SKILL_DIR` points to this skill folder.

```bash
bun --cwd "$SKILL_DIR" install
export EXA_API_KEY="your-key"
```

Scripts: run `bun --cwd "$SKILL_DIR" scripts/doctor.ts` to verify env.

References: see `references/tooling.md` for constraints and `references/flows.md` for minimal workflows.

Assets: `assets/query-templates.json` contains reusable prompt templates.

## Tools

### search

```bash
bun --cwd "$SKILL_DIR" exa.ts search "query" -n 5 --type deep --text-max 2000
```

Options:
- `-n <num>`
- `--type <auto|fast|deep>`
- `--text-max <num>`

### contents

```bash
bun --cwd "$SKILL_DIR" exa.ts contents https://example.com --text-max 2000
```

Options:
- `--text-max <num>`

### answer

```bash
bun --cwd "$SKILL_DIR" exa.ts answer "question" --text
```

Options:
- `--text`
- `--system "instruction"`
- `--schema '{"type":"object","properties":{...}}'`

### research-start

```bash
bun --cwd "$SKILL_DIR" exa.ts research-start "instructions" --model exa-research
```

Options:
- `--model <exa-research|exa-research-pro>`

### research-check

```bash
bun --cwd "$SKILL_DIR" exa.ts research-check <task-id>
```

### deep-search

```bash
bun --cwd "$SKILL_DIR" exa.ts deep-search "objective" --queries "a,b,c"
```

Options:
- `--queries a,b,c`

### code-context

```bash
bun --cwd "$SKILL_DIR" exa.ts code-context "query"
```

Options:
- `--tokens <1000-50000>` (default 50000)

### company-research

```bash
bun --cwd "$SKILL_DIR" exa.ts company-research "company name" -n 3
```

Options:
- `-n <num>`

### linkedin-search

```bash
bun --cwd "$SKILL_DIR" exa.ts linkedin-search "query" --type profiles -n 3
```

Options:
- `--type <profiles|companies|all>`
- `-n <num>`
