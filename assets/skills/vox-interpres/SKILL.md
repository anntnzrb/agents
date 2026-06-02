---
name: vox-interpres
description: Human-to-song interface using deterministic audio analysis + Q&A. Trigger this whenever the user wants to talk to a song/audio file, ask what is happening in a track, detect tempo/key/sections/energy, inspect metadata/codec, compare segments, or run conversational analysis on MP3/FLAC/WAV/OGG/M4A.
license: GPL-3.0-or-later
compatibility: Requires `uv`, `ffmpeg`/`ffprobe`, and local audio files.
metadata:
  author: anntnzrb
allowed-tools: ""
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

## Read only what you need

- Operational recipes: `cookbook/basics.md`
- Question design + intent coverage: `cookbook/question-patterns.md`
- Advanced workflows + power-user flows: `cookbook/advanced-workflows.md`
- Command quick reference: `references/cheatsheet.md`
- JSON/output semantics: `references/output-contract.md`
- Failure recovery: `references/troubleshooting.md`
- Future expansions (explicitly not yet implemented): `references/roadmap.md`

## Validation assets

- Prompt set for skill checks: `evals/evals.json`
- Validation report: `references/skill-creator-validation.md`
