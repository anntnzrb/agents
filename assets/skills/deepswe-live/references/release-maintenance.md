# Release and data maintenance

Read this when a new DeepSWE release is announced, when the upstream reruns a
benchmark under an existing version, or when the default release must move.

## Two different update cases

### Updated data under the same version

A benchmark version is a release/schema namespace, not an immutable data
snapshot. If DeepSWE reruns models and republishes `v1.1` with new values:

1. Do **not** change the version in the skill
2. Run a live command such as `report` or `fetch` with `--version v1.1`
3. The client requests the same canonical artifact URL and sends cached `ETag`
   and/or `Last-Modified` validators when available.
4. A `200` response replaces the cached payload. A `304` response reuses the
   exact cached bytes because the upstream says the payload is unchanged.
5. Check the returned `generated_at` (upstream data time), `fetched_at` (local
   fetch/revalidation time), validator metadata, and row counts.

The cache is an HTTP optimization, not a freshness decision: live metric
commands revalidate on every invocation. They do not continuously poll in the
background. If the upstream changes bytes without changing its validators and
returns an incorrect `304`, conditional HTTP cannot detect that error.

### A new benchmark version

For a concrete release such as `v1.12` or `v2.0`:

1. Confirm the canonical artifact exists at:
   `https://deepswe.datacurve.ai/artifacts/{version}/leaderboard-live.json`.
2. Fetch it explicitly before changing any default:

   ```text
   uv run --script <skill-dir>/scripts/cli.py fetch --version v1.12
   ```

3. Confirm the response is successful JSON and that its payload, URL, and
   provenance all agree on the same concrete version. If raw trials are needed,
   fetch them explicitly with `--trials`; never download task or artifact data.
4. Run the report against the explicit version and inspect counts, fields, CI
   values, `generated_at`, and `fetched_at`:

   ```text
   uv run --script <skill-dir>/scripts/cli.py report --version v1.12
   ```

5. Decide whether `latest` should move. Resolution order is:
   `DEEPSWE_DEFAULT_VERSION`, then the code default in
   `lib/deepswe/sources.py` (`v1.1` unless deliberately changed). Prefer the
   environment override for deployment-specific rollout; change the code
   default only when the repository's default release should move.
6. Update version-specific fixtures, expected values, examples, and evals only
   when they intentionally assert the old default. Do not rewrite historical
   snapshots or mix rows from different releases.

Explicit semantic versions, including future minor, patch, prerelease, and
major releases, are accepted. Major-only identifiers such as `v1` are not.
Never infer a version from a homepage or silently map an unknown release to
`latest`.

## Cache and historical data

The default persistent cache is `~/.cache/deepswe`; fetched artifacts default to
its `artifacts` subdirectory. Override these locations with `--cache-dir` and
`--output-dir`. To perform an isolated full fetch without using existing
validators, provide a fresh `<temp-dir>` cache and output directory rather than
deleting a user's cache.

`--snapshot <path>` intentionally reads historical local data and performs no
live fetch. A snapshot must prove its concrete benchmark version through its
payload metadata or a versioned path. `--allow-stale` is also explicit and
marks reused data as stale; neither mode is appropriate for verifying a new
release.

## Maintenance gate

From the repository root, run the smallest relevant checks after a release or
runtime change:

```text
uv run --script assets/skills/deepswe-live/scripts/cli.py --help
uv run --with pytest --python 3.12 pytest assets/skills/deepswe-live/tests
uvx ruff format assets/skills/deepswe-live
uvx ruff check --select ALL --ignore COM812,D203,D213 assets/skills/deepswe-live
uv run --script assets/skills/skill-creator/scripts/cli.py quick-validate assets/skills/deepswe-live
git diff --check
```

If Ruff reports pre-existing violations outside a documentation-only change, record the gate failure and do not broaden a release update into unrelated cleanup.

A failed fetch, schema check, version check, or mixed-version check is a
release-blocking error. Do not paper over it with stale data.
