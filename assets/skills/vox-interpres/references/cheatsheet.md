# vox-interpres cheatsheet

## Core commands

```bash
# full analysis
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac --json

# force recompute
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac --refresh --json

# no cache
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac --no-cache --json

# ask one question
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" ask ./song.flac "tempo and key?"

# interactive mode
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" chat ./song.flac

# segment analysis
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac \
  --segment-start 45 --segment-duration 20 --json

# generate plots
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac --plots --json
```

## Shared options (`analyze`, `ask`, `chat`)

- `--segment-start <seconds>`
- `--segment-duration <seconds>`
- `--plots`
- `--out-dir <path>`
- `--cache` / `--no-cache`
- `--refresh`

## Analyze-only option

- `--json`

## Supported audio extensions

- `.mp3`, `.flac`, `.wav`, `.ogg`, `.m4a`

## Quick jq snippets

```bash
jq '{tempo:.beats.tempo_bpm,key:(.key.key+" "+.key.mode),kconf:.key.confidence}' <temp-dir>/analysis.json
jq '.metadata | {codec,container,sample_rate_hz,channels,bit_rate}' <temp-dir>/analysis.json
jq '.section_hints | length' <temp-dir>/analysis.json
```
