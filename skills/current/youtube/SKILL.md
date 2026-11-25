---
name: youtube
description: "Use when downloading YouTube media or subtitles via yt-dlp, or for YouTube Data API playlist, video, or search tasks."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# YouTube: yt-dlp for media, cli.py for the Data API

Two tools, two jobs. yt-dlp downloads media and subtitles; it cannot write to a
user account. `scripts/cli.py` owns YouTube Data API v3 account operations:
playlist creation, filling, item add/remove, description updates, video
metadata, and search.

## Media download (yt-dlp)

Before every operation, run `yt-dlp --version`. If unavailable, quit; the user
installs it manually. For subtitle downloads YouTube rate-limits datacenter and
residential IPs quickly (HTTP 429); `--cookies-from-browser <browser>` with an
active YouTube session is the reliable workaround.

For specific options or unfamiliar requests, fetch the reference and search it:

```bash
curl -s https://raw.githubusercontent.com/yt-dlp/yt-dlp/refs/heads/master/README.md -o <temp-dir>/yt-dlp-docs.md
```

Simple requests run directly with known options; complex ones fetch docs first.

## Data API operations (scripts/cli.py)

```text
uv run --script skills/current/youtube/scripts/cli.py <command> [options]
```

Commands:

- `auth bootstrap [--redirect-url URL]`: one-time headless consent. Prints an
  authorization URL openable on any device; the browser redirects to a dead
  localhost URL; paste that full URL back with `--redirect-url`. Exchanges the
  code, stores `client_id`/`client_secret`/`refresh_token` in
  `${XDG_CONFIG_HOME:-~/.config}/yt/oauth.json` (mode 0600) and prints the
  three environment variables. Run once ever, on any machine.
- `auth status`: verify credentials; returns the owning channel title.
- `playlists list`: own playlists as JSON.
- `playlists items <id-or-title-prefix>`: playlist contents as JSON
  (position, video id, title), fully paginated.
- `playlists add <id-or-title-prefix> <video>...`: insert videos, skipping
  ones already present; reports `added` vs `skipped`. Videos accept bare ids,
  `youtube.com/watch?v=ID`, `youtu.be/ID`, and `youtube.com/shorts/ID` forms.
- `playlists remove <id-or-title-prefix> <video>...`: delete the playlist
  items for the given videos; reports `removed` vs `not_found`.
- `playlists apply <manifest.tsv> [--privacy private|unlisted|public]`:
  create missing playlists and insert missing videos, idempotent. Manifest
  columns: `playlist_title<TAB>video_id[<TAB>note]`; `#` lines are comments.
- `playlists notes <id-or-title-prefix> --file <path>`: replace a playlist
  description with file contents (5000 character API limit).
- `videos info <video>...`: title, channel, ISO 8601 duration, publishedAt;
  ids batch 50 per API call, same id/URL forms as `playlists add`.
- `search <query> [--limit N]`: video search, default 5 results, cap 25.
  Expensive: 100 quota units per call; prefer `videos info` for known ids.

## Credentials

Refresh tokens are portable across machines: bootstrap once, copy the file or
the environment variables everywhere, including headless SSH servers. The CLI
never runs a browser flow on the machine it executes on.

Resolution order:

1. Environment variables `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`
2. XDG file `${XDG_CONFIG_HOME:-~/.config}/yt/oauth.json`

The Google Cloud OAuth consent screen MUST be in production mode. Testing-mode
refresh tokens expire after 7 days and break headless automation weekly.
Production mode shows an unverified-app warning once per account; accepting it
is the cost of self-use sensitive scopes. The OAuth client type is Desktop app.

Output contract: stdout carries exactly one JSON object per invocation,
`ok:true` or `ok:false` with a stable uppercase error code. Intended use is
both interactive and scripted.

## Watch Later limitation

The Data API cannot write to Watch Later since September 2020; inserts into the
`WL` playlist id return an official error. Ordered private playlists are the
correct replacement. No workaround exists; do not attempt one.
