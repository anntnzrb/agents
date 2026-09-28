---
name: youtube
description: "Use when downloading or extracting YouTube videos, audio, subtitles, or media URLs with yt-dlp, not for web scraping."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# yt-dlp Video Downloader Skill

Use `yt-dlp` CLI to download and process videos from YouTube and other platforms.

## Availability

Before every operation, run `yt-dlp --version`. If unavailable, quit; the user installs it manually.

## Documentation Access

For specific options/features or complex, unfamiliar requests:

1. Fetch the docs:

   ```bash
   curl -s https://raw.githubusercontent.com/yt-dlp/yt-dlp/refs/heads/master/README.md -o <temp-dir>/yt-dlp-docs.md
   ```

2. Search the docs using a read-only subagent to preserve the context window when supported, or inspect the file directly:
   - Read `<temp-dir>/yt-dlp-docs.md` to find information about `[SPECIFIC TOPIC]`.
   - Extract only the relevant options and examples.

## Workflow

Simple requests → execute directly with known options.
Complex/unfamiliar requests → fetch docs → subagent search → execute.

## Guidelines

- Verify installation first.
- Delegate extensive doc searches to a subagent.
- Always show the command being run.
- Explain common issues (geo-restrictions, age-gates, etc.).
