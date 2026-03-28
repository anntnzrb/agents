# RPC

Minimal Pi-inspired JSONL RPC for the bundled skill-local CLI. Not full Pi RPC.

## Transport

- one JSON object per stdin line
- one JSON object per stdout line
- request field: `type`
- legacy request alias: `command`
- response envelope uses `type: "response"` + `command`

## Commands

### ping

Request:

```json
{"id":"1","type":"ping"}
```

Response:

```json
{"id":"1","type":"response","command":"ping","success":true,"data":{"ok":true,"version":"1"}}
```

### get_schema

Request:

```json
{"id":"2","type":"get_schema"}
```

Use before building integrations.

### search

Request shape:

```json
{
  "id": "3",
  "type": "search",
  "query": "usb c to usb c braided cable",
  "page": 1,
  "pages": 1,
  "amazonSort": null,
  "minRating": 4.5,
  "maxPrice": 10,
  "badge": null,
  "titleContains": null,
  "include": ["braided"],
  "exclude": ["usb a", "lightning"],
  "limit": 5,
  "htmlPath": null,
  "details": true,
  "detailLimit": 2,
  "scoring": true,
  "zipCode": "33101"
}
```

Response success:

```json
{
  "id": "3",
  "type": "response",
  "command": "search",
  "success": true,
  "data": {"type": "amz-live.search_results", "results": []}
}
```

Response error:

```json
{
  "id": "3",
  "type": "response",
  "command": "search",
  "success": false,
  "error": {"code": "search_error", "message": "..."}
}
```

## Good defaults

For agents, prefer:
- `details: true`
- `detailLimit: 2`
- `scoring: true`
- `limit: 5`

Only increase `detailLimit` when the shortlist is genuinely small.

## Shell example

```bash
printf '%s\n' \
  '{"id":"1","type":"ping"}' \
  '{"id":"2","type":"search","query":"usb c to usb c braided cable","zipCode":"33101","maxPrice":10,"minRating":4.5,"include":["braided"],"exclude":["usb a","lightning"],"details":true,"detailLimit":2,"scoring":true,"limit":5}' \
  | uv run amz-live --mode rpc
```

## Integration guidance

Use RPC when:
- another agent or process needs strict envelopes
- you want schema-first integration
- shell stdout parsing is simpler than direct CLI flag parsing

Use plain CLI when:
- working manually in the skill root
- one-shot commands are enough
- you are debugging by hand
