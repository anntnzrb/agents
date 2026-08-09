# Command routing

Use this page to choose one deterministic JSON command. The CLI is a metrics/results interface, not a general DeepSWE content browser.

## Decision table

| User need | Command | Required decision |
| --- | --- | --- |
| Current model-efficiency answer | `report` | Fetch the resolved version first when freshness matters. |
| Order published configurations | `rank` | Choose one supported metric and order; preserve config identity. |
| Inspect included trial metrics | `trials` | Keep the default filter unless the user explicitly asks for an override. |
| Summary facts or supported fields | `stats` / `schema` | Treat published fields and derived fields separately. |
| Acquire local artifacts | `fetch` | Fetch leaderboard by default; add `--trials` only for raw-trial work. |
| Historical comparison | `compare` | Supply explicit local snapshots; both must identify the same version. |

## Version resolution

- Omitted version and `latest` use one central default: `DEEPSWE_DEFAULT_VERSION`, or configured `v1.1` when the environment variable is absent
- Explicit semantic versions `v1.1+` are supported. A semantic version means a `v` major/minor release (and an optional patch component when accepted by the CLI), not a homepage label
- Reject major-only values such as `1` or `v1`; never fetch legacy v1
- Resolve once and use the resulting version for every artifact in the request. Never discover a “latest” value from a homepage or mix versioned paths
- On an invalid version, return a JSON error envelope; do not attempt a fallback

## Fresh fetch versus local data

1. Use `fetch` for current data. The default artifact is `leaderboard-live.json`; `--trials` opts into `trials.json`
2. For `report`, `rank`, `stats`, or `trials`, use a fresh fetch when currentness is part of the question. The CLI may manage its configured cache/output directories
3. Use `--snapshot <path>` only when a historical local artifact is intended. Preserve the snapshot's version and freshness metadata in the result
4. Use `--allow-stale` only as an explicit stale-data choice. Do not interpret a failed refresh as permission to read a last-good cache
5. If a response is `304 Not Modified`, reuse the exact validated cached artifact and its provenance. If the cache is absent, invalid, or a validator response is malformed, return an error
6. HTTP, network, malformed JSON, schema, endpoint-version, and mixed-version errors are visible errors. Do not silently downgrade to another version or file

## Analysis routing

- `report` is the primary route for “which model/configuration is most efficient?” It must retain scores, counts, CIs, raw extrema, Pareto choices, and provenance
- `report --pareto-axis metric:order` is the opt-in route for a different multi-objective frontier. Omit it to retain the default four-axis frontier
- `report --efficiency name=numerator/denominator` is the opt-in route for an explicit derived ratio. Keep the formula and null/zero-denominator reason with the result
- `rank` is for one-dimensional ordering. Use explicit quality/sample flags only when requested; defaults do not hide low-n or incomplete rows
- `trials` uses `source='deep-swe'`, `eval_scope='full'`, and `included_in_score=true` by default. Use explicit `--source`, `--eval-scope`, or `--all`/inclusion controls to widen visibility, and inspect `filters_applied`
- `stats` summarizes available metrics; `schema` is the compatibility/introspection route for future payload versions
- `compare` is snapshot-to-snapshot only and rejects differing benchmark versions

## Output discipline

Every invocation writes one compact JSON object to stdout. Check `ok` first; diagnostics are stderr. On success, read `data.scope` and `data.provenance` before interpreting rows. On failure, return the structured `error` without inventing partial metrics. See `output-contract.md` for field semantics and `provenance.md` for citation rules.
