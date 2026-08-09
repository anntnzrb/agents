# Source discovery

## Authority

The official application (`https://livebench.ai/`) is a shell. The current deferred JavaScript bundle is the authority for the selectable release array and the exact asset templates it advertises. The selector is bundle-bounded: it is not an origin-wide directory/index, and `RELEASE_DISCOVERY_LIMITED` is retained in every discovery result.

The adapter fetches the shell, extracts its official same-origin bundle URL, extracts release IDs in advertised order, and resolves `latest` to the last advertised entry. Bundle/deployment timestamps and cache-busting query values are transport metadata, not release IDs.

## Target planning

A resolved release is atomic:

- required `table_<release with hyphens replaced by underscores>.csv`;
- required `categories_<same>.json`;
- optional `cost_<same>.csv`, only when the bundle advertises that target.

Every target carries the same release ID, exact URL, discovered-from authority URL, expected content type, and required/optional status. Table/category failure is a release failure. Cost HTTP 404 is recorded as absent with attempted URL; it is never backfilled from another release.

An explicit unadvertised release is allowed only with exact caller-supplied official asset URLs/manifest. The implementation allows fixture/file URLs for local deterministic snapshots and official HTTPS hosts for live targets; it never guesses directory listings or filenames.

## Separate source surfaces

The application leaderboard assets are distinct from the official repository, Hugging Face datasets, paper, and datasheet. Those surfaces can corroborate methodology or historical questions but cannot replace an application release score/cost asset.
