---
name: youtube
description: "Use when a YouTube or media URL must be inspected, downloaded, converted, extracted, listed, or explored."
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

2. Use a **subagent** to search the docs (preserves context window):

   ```
   task(
     subagent_type="explore",
     description="Search yt-dlp docs",
     prompt="Thoroughness: quick

   Read <temp-dir>/yt-dlp-docs.md and find information about [SPECIFIC TOPIC].
   Return only the relevant options and examples."
   )
   ```

## Workflow

Simple requests → execute directly with known options.
Complex/unfamiliar requests → fetch docs → subagent search → execute.

## Guidelines

- Verify installation first.
- Delegate extensive doc searches to a subagent.
- Always show the command being run.
- Explain common issues (geo-restrictions, age-gates, etc.).
