# vox-interpres troubleshooting

## 1) `uv not found in PATH`

Symptom:

- wrapper exits with `vox-interpres: uv not found in PATH`

Fix:

- install uv
- ensure shell PATH includes uv binary

## 2) `audio file not found`

Symptom:

- path typo or wrong working directory

Fix:

- use absolute path
- check file exists and extension is supported

## 3) `unsupported audio format`

Symptom:

- extension not in allowed set

Fix:

- convert with ffmpeg to supported extension, e.g. `.wav` or `.flac`

## 4) librosa load fails

Behavior:

- tool auto-attempts ffmpeg fallback transcoding to temp wav

If still failing:

- verify ffmpeg works: `ffmpeg -version`
- validate source file: `ffprobe -v error -show_format -show_streams <file>`
- try segment analysis first (`--segment-duration 20`) in case file has corrupt tail

## 5) ffprobe metadata empty/null

Possible causes:

- ffprobe missing
- malformed container
- minimal metadata tags

Fix:

- install/repair ffprobe
- re-encode file with ffmpeg

## 6) key confidence is low

This is common on:

- atonal/percussive/noisy tracks
- heavy modulation
- short segments

Fix:

- analyze longer segment or full track
- compare multiple segments
- treat result as estimate, not truth

## 7) wrong/odd section labels

Section labeling is heuristic, deterministic, and coarse.

Fix:

- use section boundaries and confidence as signals
- ignore label text if needed; use time boundaries only

## 8) plots not generated

Symptom:

- `--plots` used, but no files

Fix:

- install plot dependency (`matplotlib`)
- check writable `--out-dir`
- inspect `notes` in JSON for reason

## 9) stale cache behavior

Symptoms:

- output seems old after logic updates

Fix order:

1. run with `--refresh`
2. use `--no-cache`
3. clear the cache directory reported by the CLI

## 10) reproducibility checklist

- pin same input file
- pin same segment window
- use `--refresh` during verification
- record tool versions from `notes`
