# JSONL RPC reference

Read this when sending multiple searches through one CLI process.

## Invocation

```text
uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

Each non-empty stdin line is one JSON object.
Each request receives one flushed JSON response on stdout.
Malformed requests do not stop subsequent lines.
Use `type` for the command. `command` is also accepted.
Commands are `ping`, `get_schema`, and `search`.

## Requests

```json
{"id":"health","type":"ping"}
{"id":"schema","type":"get_schema"}
{"id":"deals","type":"search","query":"sony wh-1000xm5","buyItNow":true,"condition":"used","exclude":["case","parts"],"limit":5,"scoring":true,"details":true,"detailLimit":1}
```

Request fields use camelCase: `minPrice`, `maxPrice`, `buyItNow`, `perPage`,
`zipCode`, `titleContains`, `minSellerFeedback`, `freeShipping`, `detailLimit`,
and `htmlPath`. Other CLI controls keep their one-word names.
`include` and `exclude` accept a string or an array of strings.
`get_schema` publishes the complete supported request-field list.

## Responses

```json
{"id":"health","type":"response","command":"ping","success":true,"data":{"ok":true,"version":"1"}}
{"type":"response","command":"unknown","success":false,"error":{"code":"parse_error","message":"Invalid JSON request"}}
```

Successful searches return the LLM envelope under `data`.
Errors contain `code` and `message` under `error`.
Codes are `parse_error`, `invalid_request`, `unknown_command`, and `search_error`.
If supplied, a valid `id` is echoed, including null.
RPC parameter errors are response data. The process exits 0 when stdin closes.
