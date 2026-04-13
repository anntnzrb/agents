# vox-interpres roadmap (ideas)

Status legend:
- ✅ implemented
- 🧪 proposed

## Current core

- ✅ deterministic Q&A intents (tempo/key/beats/duration/energy/spectral/sections/metadata)
- ✅ segment analysis
- ✅ cache + refresh controls
- ✅ ffmpeg fallback decode path
- ✅ ffprobe metadata
- ✅ optional plots

## High-value near-term

- 🧪 `ask --json` and `chat --json` machine-readable responses
- 🧪 `--why` flag: include matched intent tokens and routing explanation
- 🧪 `--list-intents` command for discoverability
- 🧪 cache key versioning by analyzer/schema version
- 🧪 `compare` command for two tracks (tempo/key/energy diff report)

## Musical depth upgrades

- 🧪 beat timestamp export and beat phase descriptors
- 🧪 novelty-curve section detector (better structure hints)
- 🧪 chord progression hints (coarse, confidence-scored)
- 🧪 onset density and groove fingerprints
- 🧪 spectral band energy buckets (sub/bass/mid/high)

## Human-interface upgrades

- 🧪 bilingual intent lexicon (Spanish+English tokens)
- 🧪 timeline Q&A (`what happens at 1:42?`)
- 🧪 persona modes (producer view, DJ view, composer view)
- 🧪 confidence-aware answer templates for uncertain metrics

## Automation upgrades

- 🧪 folder batch mode with consolidated CSV/JSONL
- 🧪 playlist-fit scoring (tempo/key/energy compatibility)
- 🧪 deterministic RPC mode for agent orchestration
- 🧪 report generator (HTML/Markdown artifact with plots)

## Out-of-scope for this deterministic core

- lyric transcription (needs ASR)
- subjective emotion generation as hard truth
- legal ownership identification
- source separation quality guarantees without dedicated models
