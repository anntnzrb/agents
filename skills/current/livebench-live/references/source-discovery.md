# Source discovery

## Authority

`https://livebench.ai/` official application = shell. Current deferred JavaScript bundle = authority for selectable release array and exact advertised asset templates. Discovery bundle-bounded, not origin-wide directory/index; every discovery result retains `RELEASE_DISCOVERY_LIMITED`.

Adapter: fetch shell → extract official same-origin bundle URL → extract release IDs in advertised order; `latest` = last advertised entry. Bundle/deployment timestamps and cache-busting query values = transport metadata, not release IDs.

## Target planning

Resolved release = atomic:

- required `table_<release with hyphens replaced by underscores>.csv`;
- required `categories_<same>.json`;
- optional `cost_<same>.csv`, only when bundle advertises target.

Every target carries the same release ID, exact URL, discovered-from authority URL, expected content type, and required/optional status. Table/category failure = release failure. Cost HTTP 404 = absent, with attempted URL; NEVER backfill from another release.

Explicit unadvertised release allowed only with exact caller-supplied official asset URLs/manifest. Fixture/file URLs allowed for local deterministic snapshots; official HTTPS hosts allowed for live targets. NEVER guess directory listings or filenames.

## Separate source surfaces

Application leaderboard assets distinct from official repository, Hugging Face datasets, paper, and datasheet. Those surfaces may corroborate methodology or historical questions but cannot replace an application release score/cost asset.
