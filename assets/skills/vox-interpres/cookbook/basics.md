# vox-interpres cookbook: basics

Practical recipes for using vox-interpres as a human-to-song interface.

## 1) Preflight

```bash
command -v uv
command -v ffmpeg
command -v ffprobe
```

If one is missing, fix that first.

## 2) Analyze full song

```bash
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --json
```

Outputs:
- JSON analysis payload (stdout)
- cache file under `~/.cache/vox-interpres/`

## 3) Ask quick questions (single shot)

```bash
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" ask ./song.flac "tempo and key?"
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" ask ./song.flac "how energetic is this?"
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" ask ./song.flac "show metadata"
```

## 4) Chat mode (interactive)

```bash
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" chat ./song.flac
```

Inside REPL:
- ask natural questions
- type `exit`, `quit`, or `:q` to end

## 5) Analyze only a segment

```bash
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac \
  --segment-start 60 \
  --segment-duration 30 \
  --json
```

Use this for “what happens at minute 1?” style analysis.

## 6) Force recompute / bypass cache

```bash
# force recompute
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --refresh

# do not read/write cache
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac --no-cache
```

## 7) Generate plots (waveform/spectrogram/chroma)

```bash
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze ./song.flac \
  --plots \
  --out-dir ~/.cache/vox-interpres \
  --json
```

Plot file paths appear in `plot_files`.

## 8) Compare two songs quickly

```bash
A=./song-a.flac
B=./song-b.flac

sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze "$A" --json > /tmp/a.json
sh "$SKILLS_DIR/vox-interpres/scripts/vox-interpres.sh" analyze "$B" --json > /tmp/b.json

jq '{tempo:.beats.tempo_bpm,key:(.key.key+" "+.key.mode),energy:.energy.dynamic_range}' /tmp/a.json
jq '{tempo:.beats.tempo_bpm,key:(.key.key+" "+.key.mode),energy:.energy.dynamic_range}' /tmp/b.json
```

## 9) Agent pattern (human asks, agent executes)

Recommended loop:
1. Human gives file path + question.
2. Agent runs `ask` for direct answer.
3. If low confidence / broad query, agent runs `analyze --json`.
4. Agent answers with metrics + caveats.
5. For follow-up detail, agent switches to `chat`.

## 10) What this tool is great at

- Fast objective descriptors from audio signal.
- Deterministic Q&A on fixed intents.
- Segment-aware inspection.
- Repeatable outputs suitable for automation.

## 11) What this tool is **not** (yet)

- No lyric transcription.
- No chord-by-chord progression output.
- No source separation/stems.
- No semantic mood classification model.

Use `references/roadmap.md` for extension ideas.
