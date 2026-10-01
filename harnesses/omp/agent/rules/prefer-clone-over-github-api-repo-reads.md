---
name: prefer-clone-over-github-api-repo-reads
description: "Read remote repo source, READMEs, and metadata from a vendored or shallow clone, not repeated `gh api`/`gh repo view`/`curl` calls to GitHub"
condition: ["\\bgh\\s+api\\s+(?:-\\S+\\s+)*/?repos/[\\w.-]+/[\\w.-]+(?:/(?:readme|contents|git/trees|git/blobs|tarball|zipball|commits)\\b|[\\s'\"]|$)", "\\bgh\\s+repo\\s+view\\b", "\\b(?:curl|wget)\\b[^\\n]*?\\b(?:api\\.github\\.com/repos/[\\w.-]+/[\\w.-]+|raw\\.githubusercontent\\.com/[\\w.-]+/[\\w.-]+|github\\.com/[\\w.-]+/[\\w.-]+/(?:raw|blob|archive)/)"]
scope: "tool"
---

Don't read a GitHub repo's content or metadata with repeated `gh api repos/<owner>/<repo>/...`, `gh repo view`, or `curl`/`wget` calls to `api.github.com`, `raw.githubusercontent.com`, or `github.com/.../raw|blob|archive`. They burn rate-limited quota fast and fetch one file at a time.

Do this instead:
1. Look in the vendored repo directory for an existing checkout and use it. Pull first if it might be stale.
2. If there's no checkout and the source is worth keeping, shallow-clone it into the vendored repo directory with `git clone --depth 1 https://github.com/<owner>/<repo> <dir>`. For a one-off look, shallow-clone into a temp dir instead.
3. Read the README, source, and docs locally with `read`, `grep`, and `glob`. Get recent activity from `git log -1 --format=%cI` in the clone.

Use `gh api` only for data that isn't in git: issues, PRs, stars, releases. Batch those into one GraphQL query or one `--jq` call. Never page through files over HTTP.