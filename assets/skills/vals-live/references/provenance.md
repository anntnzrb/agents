# Provenance, cache, and freshness

The cache is append-only and content-addressed. Each successful artifact stores exact raw bytes at a SHA-256 path plus a manifest/sidecar containing source URL, discovery URL, final URL, status, content type, ETag, Last-Modified, fetched/observed UTC timestamps, release identity, hash, length, parser/version, and raw-byte reference. Authorization and cookie headers are never persisted or emitted.

The default root follows platform conventions: macOS `~/Library/Caches/vals-live`, Linux `$XDG_CACHE_HOME/vals-live` or `~/.cache/vals-live`, Windows `%LOCALAPPDATA%/vals-live/Cache`; `--cache-dir` and `VALS_CACHE_DIR` override it. There is no automatic eviction.

A refresh sends both `If-None-Match` and `If-Modified-Since` when validators exist. A `304` reuses exact matching bytes only when the URL/release index and validator are valid; otherwise it fails with `CACHE_MISSING` or `CACHE_VALIDATOR_INVALID`. Failed refreshes do not overwrite cached bytes.

Default refresh failure is a visible error. `--allow-stale` explicitly serves only the matching cache artifact and emits `STALE_DATA`, `stale:true`, and `freshness.mode:"stale-cache"`. An explicit `--snapshot` is historical, not outage-stale: `historical:true`, `stale:false`, and `freshness.mode:"snapshot"`. An older release, benchmark version, or last-good artifact is never implicit.

Raw bytes are referenced by manifest; they are not inlined in normal command output. Every metric evidence object points back to the immutable artifact hash and exact source path.
