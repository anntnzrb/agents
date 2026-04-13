# vox-interpres output contract

`analyze --json` emits a single `AnalysisResult` object.

## Top-level fields

- `schema_version` (int)
- `generated_at` (ISO timestamp)
- `file_path` (string)
- `segment_start_s` (float)
- `segment_duration_s` (float|null)
- `analysis_duration_s` (float)
- `sample_rate_hz` (int)
- `metadata` (object)
- `key` (object)
- `beats` (object)
- `spectral` (object)
- `energy` (object)
- `section_hints` (array)
- `notes` (array)
- `plot_files` (array)

## Metadata

`metadata` comes from `ffprobe` when available.

Fields:
- `container`
- `codec`
- `sample_rate_hz`
- `channels`
- `bit_rate`
- `duration_s`
- `tags` (map)

If ffprobe fails/missing, these may be null/empty.

## Key estimate

`key` fields:
- `key` (pitch class)
- `mode` (`major`/`minor`)
- `confidence` (0..1, relative confidence)
- `chroma_profile` (12-element normalized profile)

Important: this is heuristic global-key estimation, not frame-level harmonic truth.

## Beats

`beats` fields:
- `tempo_bpm`
- `beat_count`
- `first_beat_s`
- `last_beat_s`

## Spectral stats

Each block (`centroid`, `bandwidth`, `rolloff`, `flatness`) includes:
- `mean`, `std`, `minimum`, `maximum`, `p10`, `p90`

## Energy dynamics

- `rms` (stats block)
- `dynamic_range`
- `low_energy_ratio`
- `high_energy_ratio`

## Section hints

`section_hints` entries:
- `start_s`
- `end_s`
- `label`
- `confidence`

Labels are heuristic (`intro/verse/chorus/...`) and should be treated as hints, not annotations.

## Notes

`notes` may include:
- ffmpeg/ffprobe version lines
- fallback decode information (if ffmpeg transcode was used)
- plot generation notes

## Cache behavior

Cache key uses:
- resolved file path
- file size + mtime
- segment start + duration

So changing file content/time or segment window creates a new cache entry.
Use `--refresh` when in doubt.
