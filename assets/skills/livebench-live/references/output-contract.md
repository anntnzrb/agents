# Output contract

Every invocation writes one compact JSON object to stdout. Success is:

```json
{"ok":true,"schema_version":"1","command":"leaderboard","data":{"scope":{},"value_status":"published","rows":[],"warnings":[],"provenance":{}}}
```

Failure is:

```json
{"ok":false,"schema_version":"1","command":"leaderboard","error":{"code":"SOURCE_UNAVAILABLE","message":"...","details":{}}}
```

`schema_version` is the string `"1"`. `command` is present on failures. Human/progress diagnostics are stderr-only; result-affecting warnings are in `data.warnings`/`data.diagnostics`, and failed sources do not become empty successful tables. `null` is unavailable, never a zero default.

Numeric fields retain raw value, normalized value or null, unit, normalization note, source path, value status, semantic status, and artifact evidence. Derived values live under `derived`; published source cells are never overwritten. Dynamic maps/lists preserve unknown fields and labels.
