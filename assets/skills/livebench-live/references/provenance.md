# Provenance and freshness

The default cache follows platform conventions: macOS `~/Library/Caches/livebench-live`, Linux `$XDG_CACHE_HOME/livebench-live` or `~/.cache/livebench-live`, Windows `%LOCALAPPDATA%/livebench-live`; `LIVEBENCH_CACHE_DIR` and `--cache-dir` override it. Retention is immutable with no automatic eviction.

Raw bytes are content-addressed by SHA-256 under a release/artifact directory. A manifest/sidecar records exact URL, discovered-from URL, release, status, content type, ETag, Last-Modified, fetch/observation times, hash, length, parser metadata, and raw-byte reference. Credentials, cookies, authorization, and API-key headers are never persisted or emitted; auth failures become redacted `SOURCE_AUTH_REQUIRED`.

Conditional requests send both `If-None-Match` and `If-Modified-Since` when available. A `304` reuses exact bytes only if a matching release/URL/artifact cache entry and validator exist; otherwise `CACHE_MISSING` or `CACHE_VALIDATOR_INVALID` fails. A failed refresh is an error by default. `--allow-stale` explicitly serves a matching cache as `freshness.mode: stale-cache`, `stale:true`, with `STALE_DATA`. `--snapshot` is historical (`freshness.mode: snapshot`, `historical:true`, `stale:false`) and is never labeled as current.

Each artifact and every numeric field carries independent timestamps and source paths. A source hash or deployment `Last-Modified` is transport provenance, not an evaluation release date. Normal responses reference raw bytes through manifests; they do not inline bodies.
