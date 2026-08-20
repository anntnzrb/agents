# vox-interpres cookbook: advanced workflows

Power-user flows for humans + agents.

## 1) Time-window sweep across one song

Detect how key/energy/tempo shift over time.

```bash
FILE=./song.flac
for START in 0 30 60 90 120; do
  uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze "$FILE" \
    --segment-start "$START" \
    --segment-duration 30 \
    --json > "<temp-dir>/seg-$START.json"
  printf 'segment=%ss\n' "$START"
  jq '{tempo:.beats.tempo_bpm,key:(.key.key+" "+.key.mode),kconf:.key.confidence,energy:.energy.dynamic_range}' "<temp-dir>/seg-$START.json"
done
```

Use this to find drops, breakdowns, and modulation-like behavior.

## 2) Batch-analyze a folder

```bash
find ./music -type f \( -name '*.mp3' -o -name '*.flac' -o -name '*.wav' -o -name '*.ogg' -o -name '*.m4a' \) | while IFS= read -r f; do
  uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze "$f" --json > "<temp-dir>/$(basename "$f").json" || true
done
```

Then aggregate with `jq`.

## 3) Build a DJ-friendly shortlist

Objective: keep tracks close in tempo and compatible key region.

```bash
# pseudo: run analyze on all tracks, then filter
jq -s '[.[] | {file:.file_path,bpm:.beats.tempo_bpm,key:(.key.key+" "+.key.mode),kconf:.key.confidence}]' <temp-dir>/*.json
```

Use ±3 BPM windows, and prefer key confidence > 0.25 when matching.

## 4) Agent mediation protocol (recommended)

For each user question:

1. If scope small: run `ask` directly
2. If scope broad/ambiguous: run `analyze --json` first
3. Answer with explicit evidence fields
4. If user asks "why?", quote raw metrics
5. If user asks "at specific time", run segment analysis

## 5) Plot-driven review

```bash
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac --plots --json > <temp-dir>/song.json
jq '.plot_files' <temp-dir>/song.json
```

Use plots for:

- waveform density changes
- spectral mass movement
- chroma concentration trends

## 6) Failure-resilient decode path

When standard load fails, vox-interpres uses ffmpeg fallback transcoding automatically.
Inspect `notes` in JSON to verify fallback path happened.

## 7) Reproducible report artifact

```bash
OUT=./report
mkdir -p "$OUT"
uv run --script "$SKILLS_DIR/vox-interpres/scripts/cli.py" analyze ./song.flac --plots --json > "$OUT/analysis.json"
```

Now you have a portable packet:

- analysis JSON
- plot PNGs
- deterministic fields for downstream automation

## 8) Extension blueprints (not implemented yet)

Potential upgrades:

- beat timestamp export (`--beats-json`)
- machine-readable ask/chat output (`--json`)
- richer section detector (novelty curve / recurrence)
- bilingual intent lexicon (Spanish + English)
- plugin commands: compare, timeline, playlist-fit

See `references/roadmap.md` for full list.
