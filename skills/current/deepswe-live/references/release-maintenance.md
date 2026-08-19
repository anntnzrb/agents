# Release/data maintenance

Use when a DeepSWE release is announced, upstream republishes data under an existing version, or the default release may change.

## Same-version data refresh

A benchmark version is a release/schema namespace, not an immutable snapshot. If upstream republishes (for example) `v1.1`:

1. **Do not change the skill's version.**
2. Run live `report` or `fetch` with `--version v1.1`.
3. The client uses the same canonical artifact URL and, when available, sends cached `ETag` and/or `Last-Modified` validators.
4. `200` replaces the cached payload; `304` reuses the exact cached bytes because upstream says they are unchanged.
5. Check `generated_at` (upstream data time), `fetched_at` (local fetch/revalidation time), validator metadata, and row counts.

Cache = HTTP optimization, not freshness authority. Live metric commands revalidate every invocation; they do not background-poll. Conditional HTTP cannot detect upstream changing bytes while leaving validators unchanged and incorrectly returning `304`.

## New benchmark version

For a concrete release such as `v1.12` or `v2.0`:

1. Confirm the canonical artifact exists at `https://deepswe.datacurve.ai/artifacts/{version}/leaderboard-live.json`.
2. Fetch explicitly before changing any default:

```text
uv run --script <skill-dir>/scripts/cli.py fetch --version v1.12
```

3. Confirm successful JSON; payload, URL, and provenance must all agree on one concrete version. If raw trials are needed, use `--trials` explicitly; **never** download task or artifact data.
4. Report against the explicit version and inspect counts, fields, CI values, `generated_at`, and `fetched_at`:

```text
uv run --script <skill-dir>/scripts/cli.py report --version v1.12
```

5. `latest` resolution: `DEEPSWE_DEFAULT_VERSION` > code default in `lib/deepswe/sources.py` (`v1.1` unless deliberately changed). Prefer the environment override for deployment-specific rollout; change the code default only when the repository default release should move.
6. Update version-specific fixtures, expected values, examples, and evals only when they intentionally assert the old default. Do not rewrite historical snapshots or mix rows from releases.

Explicit semantic versions; including future minor, patch, prerelease, and major versions; are accepted; major-only identifiers such as `v1` are not. Never infer a version from a homepage or silently map an unknown release to `latest`.

## Cache/historical data

- Default persistent cache: `~/.cache/deepswe`; fetched artifacts: its `artifacts` subdirectory.
- `--cache-dir` and `--output-dir` override these locations.
- For an isolated full fetch without existing validators, use fresh `<temp-dir>` cache and output directories; do not delete a user's cache.
- `--snapshot <path>` reads historical local data and performs no live fetch. It must prove its concrete benchmark version via payload metadata or a versioned path.
- `--allow-stale` is explicit and marks reused data stale. Neither snapshots nor stale mode verifies a new release.

## Maintenance gate

From repository root, run the smallest relevant checks after a release or runtime change:

```text
uv run --script skills/current/deepswe-live/scripts/cli.py --help
uv run --with pytest --python 3.12 pytest skills/current/deepswe-live/tests
uvx ruff format skills/current/deepswe-live
uvx ruff check --select ALL --ignore COM812,D203,D213 skills/current/deepswe-live
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/deepswe-live
git diff --check
```

Pre-existing Ruff violations outside documentation-only changes: record gate failure; do not broaden a release update into unrelated cleanup. Failed fetch, schema, version, or mixed-version checks are release-blocking; never paper them over with stale data.

## Immutable cache/legacy promotion

Content-addressed cache is the artifact-identity source during maintenance:

```text
artifacts/<sha256>.raw
artifacts/<sha256>.meta.json
index.json
manifests/<manifest-sha256>.json
```

Sidecar and manifest retain canonical URL, concrete benchmark version, validator headers, parser/version, byte length, SHA-256, and raw-byte reference. Raw bytes and sidecars are first-writer-wins. A source index may move to a newer digest without modifying older bytes. Legacy version-addressed-file promotion is non-destructive, marks `legacy_unverified`, and never deletes, truncates, or rewrites the caller's file. Do not clean the cache during release rollout.

## Release authority/omission boundary

`latest` follows `DEEPSWE_DEFAULT_VERSION`, then configured code default `v1.1`. DeepSWE's source contract currently has no authoritative release manifest: no homepage, directory listing, guessed path, or manifest-discovery call is permitted. If a future deployment explicitly configures an authoritative manifest, require exact concrete version, canonical artifact path, and SHA-256 agreement before using it. Otherwise preserve the configured default and return an error for unavailable explicit versions.

Never mix artifacts because shape matches. Never fetch task, exercise, release, trajectory, or trial-artifact content.

## Opt-in smoke evidence

`tests/test_live_smoke.py` is skipped unless `RUN_LIVE_SMOKE=1`. It uses temporary cache/output directories and explicit known version (`v1.1`), asserts metrics-only shape, and never asserts current row counts. When intentionally run, save evidence outside the package:

```json
{
  "command": "pytest -q tests/test_live_smoke.py",
  "resolved_version": "v1.1",
  "url": "<canonical leaderboard URL>",
  "sha256": "<response hash>",
  "status": "passed",
  "timestamp": "<RFC-3339>",
  "exit_code": 0
}
```

Do not run this smoke as an offline gate. Deterministic tests deny URL/socket network access and must remain reproducible without current release availability.
