# Skill Authoring

Read this reference when creating or materially refactoring a skill.

## Communicating With the User

Adapt to the user's technical level. Many users can follow concise coding jargon; some cannot. Use context cues.

- "evaluation" and "benchmark" are borderline but usually OK
- Explain "JSON" or "assertion" unless the user signals familiarity
- Define terms briefly when in doubt
- Reduce burden: extract intent from conversation history before asking
- Ask for confirmation before moving past ambiguous requirements

## Core Authoring Rules

### Capture intent

Start by understanding intent. If the current conversation already contains the workflow, extract the tools, step sequence, corrections, input formats, output formats, and success criteria before asking questions.

Ask only what remains unknown:

1. What should this skill enable?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?
4. Should we set up test cases to verify the skill works? Skills with objectively verifiable outputs benefit from test cases. Skills with subjective outputs often skip them. Suggest the appropriate default based on skill type, but let the user decide

### Research before writing

Ask about edge cases, input/output formats, example files, success criteria, and dependencies. Wait to write test prompts until the workflow is clear. Research docs, similar skills, or best practices when useful. Use subagents in parallel when available; otherwise research inline. Bring context back to the user instead of making them carry it.

### Write `SKILL.md`

Compose:

- **name**: Skill identifier
- **description**: Trigger contract + capability. This is the primary trigger. Put all "when to use" guidance here, not in the body. Skills tend to undertrigger, so write a pushy description with explicit contexts and nearby user phrasing
- **compatibility**: Required tools or dependencies. OPTIONAL; rarely needed
- **body**: Imperative instructions, examples, references, workflows, and resource pointers

Skill anatomy:

```text
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description required)
│   └── Markdown instructions
└── Bundled Resources (optional)
    ├── scripts/    - Executable code for deterministic/repetitive tasks
    ├── references/ - Docs loaded into context as needed
    └── assets/     - Files used in output (templates, icons, fonts)
```

### Safety and surprise

Skills MUST match the user's stated intent. They NEVER contain malware, exploit code, unauthorized-access workflows, data exfiltration, or misleading behavior. Roleplay and harmless persona skills are acceptable when accurately described.

### Writing style

Use imperative instructions. Explain why instructions matter instead of leaning on rigid MUSTs. Use RFC keywords for technical and operational constraints, not taste. Give the model enough purpose and theory of mind to generalize beyond examples. Draft, reread cold, then improve.

Define output formats with exact templates when structure matters. Use examples for transformations and style choices, but keep examples small and realistic.
