---
name: vox-interpres
description: "Analyze audio tracks: tempo, key, sections, energy, metadata, codecs, and segment comparisons."
license: GPL-3.0-or-later
compatibility: Requires `uv`, `ffmpeg`/`ffprobe`, and local audio files.
metadata:
  author: anntnzrb

---

# vox-interpres

Use this skill as the **conversation layer** between a human and an audio file.

## Trigger aggressively

Use when user says things like:

- “talk to this song”
- “what is this track doing?”
- “tempo/key/energy/structure?”
- “analyze this mp3/flac/wav/ogg/m4a”
- “chat with this audio file”

## Core rule

Do not improvise music claims without evidence. Run the CLI first, then answer.

## Entry points

- Wrapper: `uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" ...`
- Direct: `uv run --script <skill-dir>/scripts/cli.py ...`

## Fast path

```bash
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" ask ./song.flac "tempo and key?" --refresh
```

## Commands

### Analyze

```bash
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.mp3 --json
```

### Ask one question

```bash
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" ask ./song.wav "where are the sections?"
```

### Chat loop

```bash
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" chat ./song.ogg
```

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Basic operations | `cookbook/basics.md` | First use or common analysis |
| Question design | `cookbook/question-patterns.md` | Translating user intent |
| Batch/power workflows | `cookbook/advanced-workflows.md` | Advanced processing |
| Command flags | `references/cheatsheet.md` | Exact CLI syntax is needed |
| JSON semantics | `references/output-contract.md` | Consuming structured output |
| Failure recovery | `references/troubleshooting.md` | A run fails or looks stale |
| Unimplemented ideas | `references/roadmap.md` | Checking scope boundaries |
| Eval assets | `evals/evals.json`, `references/skill-creator-validation.md` | Validating this skill |
