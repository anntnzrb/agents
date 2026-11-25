# YouTube Data API v3 reference map

A compact map of the API surface for extending `scripts/cli.py`. Official
docs: `https://developers.google.com/youtube/v3` (check there first; Google
renumbers quota and retires methods without much ceremony).

Base URL: `https://www.googleapis.com/youtube/v3`. Auth: OAuth2 bearer token,
scope `https://www.googleapis.com/auth/youtube` covers reads and writes.

## Resources and methods

| Resource | list | insert | update | delete | Key `part` values |
| --- | --- | --- | --- | --- | --- |
| playlists | yes | yes | yes | yes | `snippet`, `status`, `contentDetails` (itemCount) |
| playlistItems | yes | yes | yes | yes | `snippet` (position, resourceId), `contentDetails` (note) |
| videos | yes | yes (upload) | yes | yes | `snippet`, `contentDetails` (duration), `status`, `statistics` |
| search | yes | no | no | no | `snippet` only |
| channels | yes | no | yes | no | `snippet`, `contentDetails` (relatedPlaylists), `statistics` |
| subscriptions | yes | yes | no | yes | `snippet`, `contentDetails`, `subscriberSnippet` |
| captions | yes | yes | yes | yes | `snippet` (track metadata); `download` is a separate method |
| commentThreads | yes | yes | yes | no | `snippet`, `replies` |
| activities | yes | no | no | no | `snippet`, `contentDetails` |

List endpoints paginate with `pageToken`/`nextPageToken`, `maxResults` cap 50.
`videos.list` batch-accepts up to 50 comma-separated ids in one call.

## Quota costs

Default allocation: 10,000 units/day/project, resetting midnight Pacific.
Numbers below come from the official quota table; treat them as approximate
because Google revised the model recently and may revise it again.

- Most `list` reads: 1 unit per call (each page of a paged call counts).
- Writes on playlists, playlistItems, comments, subscriptions: 50 units each,
  so `playlistItems.insert` and `playlistItems.delete` cost 50 units per video.
- `search.list`: historically 100 units per call. Under the revised model it
  sits in its own bucket capped at roughly 100 calls/day per project. Either
  way it is the most expensive read by two orders of magnitude; prefer
  `videos.list` whenever ids are already known.
- `captions`: `insert` 400, `update` 450, `list`/`delete` 50; `download` was
  around 200 historically and is absent from the current published table
  (approximate).
- `videos.insert` (upload): historically 1600 units; now also in its own
  bucket of roughly 100 calls/day (approximate).

## Hard limits and gotchas

- Watch Later and watch history cannot be written: since September 2020 the
  API rejects inserts into the `WL` playlist id and there is no history write
  endpoint at all. Ordered private playlists are the replacement.
- Playlist descriptions cap at 5000 characters; longer writes are rejected.
- Privacy statuses are exactly `private`, `unlisted`, `public`.
- OAuth consent screen in testing mode: refresh tokens expire after 7 days.
  Production mode: refresh tokens persist until revoked. This is the single
  most common cause of headless automation breaking weekly.
- playlistItems come back ordered by `snippet.position`; inserts append at the
  end unless `snippet.position` is set explicitly.
- The API allows duplicate videos in one playlist. Idempotency must be
  client-side: read the playlist first, skip ids already present.
- Deleted or private videos linger as phantom playlistItems: `resourceId` is
  still there, but the title becomes `Deleted video` or `Private video` and
  most snippet fields go empty. Filter or tolerate them; do not treat their
  presence as proof the video exists.
- `videos.list` silently omits unknown or deleted ids from the response
  instead of erroring; a missing input id means missing output entry.
- `search.list` relevance is opaque and region/language biased; it is a
  discovery tool, not a lookup tool.

## Extension recipe: adding a subcommand to cli.py

1. Write `cmd_<group>_<name>(args: _Args) -> None` next to the existing ones.
2. Reads: `api(path, "GET", token, params={...})`; paginated lists: `paged()`.
3. Writes: `api(..., "POST"/"PUT", body={...})`; DELETE takes `params={"id": ...}`.
4. Get the token once per command: `token = access_token(load_config())`.
5. Resolve playlists with `find_playlist(token, target)`; videos with `parse_video_ids()`.
6. Validate JSON with `_as_dict`/`_opt_str`/`_opt_int`; never index untyped data.
7. Emit exactly one object with `emit({...})`; errors with `raise fail("CODE", msg)`.
8. Wire argparse in `arguments()` and register in the `COMMANDS` dispatch table.
9. Extend the `_Fixture` handler in tests/test_cli.py and add a loopback test.
10. Run the skill gates before handoff (see SKILL.md).
