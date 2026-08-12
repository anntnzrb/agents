# Provenance and freshness

Cache defaults: macOS `~/Library/Caches/livebench-live`; Linux `$XDG_CACHE_HOME/livebench-live` or `~/.cache/livebench-live`; Windows `%LOCALAPPDATA%/livebench-live`. Overrides: `LIVEBENCH_CACHE_DIR`, `--cache-dir`. Retention immutable; no automatic eviction.

Raw bytes: SHA-256 content-addressed under release/artifact directory. Manifest/sidecar records exact URL, discovered-from URL, release, status, content type, ETag, Last-Modified, fetch/observation times, hash, length, parser metadata, and raw-byte reference. Credentials, cookies, authorization, and API-key headers NEVER persisted or emitted. Auth failures → redacted `SOURCE_AUTH_REQUIRED`.

Conditional requests: send both `If-None-Match` and `If-Modified-Since` when available. `304` reuses exact bytes only with a matching release/URL/artifact cache entry and validator; otherwise fails: `CACHE_MISSING` or `CACHE_VALIDATOR_INVALID`. Refresh failure: error by default. `--allow-stale` explicitly serves a matching cache as `freshness.mode: stale-cache`, `stale:true`, with `STALE_DATA`. `--snapshot`: historical, `freshness.mode: snapshot`, `historical:true`, `stale:false`; NEVER label current.

Each artifact and every numeric field: independent timestamps and source paths. Source hash or deployment `Last-Modified`: transport provenance, not evaluation release date. Normal responses reference raw bytes through manifests; NEVER inline bodies.
