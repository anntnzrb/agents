# vox-interpres cheatsheet

## Core commands

```bash
# full analysis
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --json

# force recompute
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --refresh --json

# no cache
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --no-cache --json

# ask one question
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" ask ./song.flac "tempo and key?"

# interactive mode
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" chat ./song.flac

# segment analysis
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac \
  --segment-start 45 --segment-duration 20 --json

# generate plots
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --plots --json
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
jq '{tempo:.beats.tempo_bpm,key:(.key.key+" "+.key.mode),kconf:.key.confidence}' /tmp/analysis.json
jq '.metadata | {codec,container,sample_rate_hz,channels,bit_rate}' /tmp/analysis.json
jq '.section_hints | length' /tmp/analysis.json
```
