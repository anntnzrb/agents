# RPC

Minimal Pi-inspired JSONL RPC for the bundled skill-local CLI. Not full Pi RPC.

## Transport

- one JSON object per stdin line
- one JSON object per stdout line
- request field: `type`
- legacy alias still accepted: `command`
- response envelope: `{"type":"response","command":"...","success":...}`

## Commands

### ping

Request:

```json
{ "id": "1", "type": "ping" }
```

Response:

```json
{
  "id": "1",
  "type": "response",
  "command": "ping",
  "success": true,
  "data": { "ok": true, "version": "1" }
}
```

### get_schema

Request:

```json
{ "id": "2", "type": "get_schema" }
```

Returns full schema/capability document.

### search

Required fields:

- `origin`
- `destination`
- `departStart` (ISO date)
- `departEnd` (ISO date)

Request shape:

```json
{
  "id": "3",
  "type": "search",
  "origin": "NYC",
  "destination": "MAD",
  "departStart": "2026-06-01",
  "departEnd": "2026-06-30",
  "tripType": "oneway",
  "stayMin": null,
  "stayMax": null,
  "adults": 1,
  "children": 0,
  "infants": 0,
  "cabin": "economy",
  "currency": "USD",
  "locale": "en",
  "market": "us",
  "nonstop": false,
  "maxBudget": null,
  "plannerLimit": 20
}
```

Success response carries full `flight-live.search_results` envelope.

Error response example:

```json
{
  "id": "3",
  "type": "response",
  "command": "search",
  "success": false,
  "error": {
    "code": "search_error",
    "message": "Sibling agent-browser wrapper is missing. Install both skills together."
  }
}
```

## RPC smoke test

```text
printf '%s\n' \
  '{"id":"1","type":"ping"}' \
  '{"id":"2","type":"get_schema"}' \
  '{"id":"3","type":"search","origin":"NYC","destination":"MAD","departStart":"2026-06-01","departEnd":"2026-06-30"}' \
  | uv run --script <skill-dir>/scripts/cli.py --mode rpc
```
