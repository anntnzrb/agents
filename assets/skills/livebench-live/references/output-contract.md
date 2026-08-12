# Output contract

Every invocation → one compact JSON object to stdout.

Success:

```json
{"ok":true,"schema_version":"1","command":"leaderboard","data":{"scope":{},"value_status":"published","rows":[],"warnings":[],"provenance":{}}}
```

Failure:

```json
{"ok":false,"schema_version":"1","command":"leaderboard","error":{"code":"SOURCE_UNAVAILABLE","message":"...","details":{}}}
```

`schema_version`: string `"1"`; `command` present on failures. Human/progress diagnostics → stderr only. Result-affecting warnings → `data.warnings`/`data.diagnostics`; failed sources NEVER become empty successful tables. `null`: unavailable, never a zero default.

Numeric fields retain raw value; normalized value or null; unit; normalization note; source path; value status; semantic status; artifact evidence. Derived values → `derived`; published source cells NEVER overwritten. Dynamic maps/lists preserve unknown fields and labels.
