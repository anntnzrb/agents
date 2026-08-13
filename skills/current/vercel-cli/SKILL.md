---
name: vercel-cli
description: Deploy, manage, and debug Vercel projects, environments, domains, logs, integrations, and CI/CD.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Vercel CLI

`vercel`/`vc`: deploy, manage, and develop Vercel projects from the command line. `vercel <command> -h`: full flags for any command.

## Project linking

Set `<VERCEL_CMD>` to installed `vercel` or ephemeral `bun x vercel`; examples use `vercel`.

MUST run commands from the directory containing `.vercel/` or a descendant.

- `.vercel/project.json`: created by `vercel link`; links one project; suitable for single-project repos and monorepos containing only one project.
- `.vercel/repo.json`: created by `vercel link --repo`; links a repo containing multiple projects; recommended when any project has a non-root directory such as `apps/web`.

Running from an unambiguous project subdirectory such as `apps/web/` skips the project-selection prompt. Troubleshooting: inspect `.vercel/` first and identify `project.json` versus `repo.json`; verify the team with `vercel whoami`. Wrong-team linking is a common failure.

## Quick start

```bash
vercel login
vercel link              # single project
# OR
vercel link --repo       # monorepo
vercel pull
vercel dev        # local development
vercel deploy     # preview deployment
vercel --prod     # production deployment
```

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Deployment|`references/deployment.md`|Deploying or promoting|
|Local development|`references/local-development.md`|Running locally|
|Environment variables|`references/environment-variables.md`|Reading or changing env|
|CI/CD|`references/ci-automation.md`|Automating deployment|
|Domains/DNS|`references/domains-and-dns.md`|Changing domain state|
|Projects/teams|`references/projects-and-teams.md`|Linking or scoping|
|Logs, debugging, protected previews|`references/monitoring-and-debugging.md`|Diagnosing or using `vercel curl`|
|Blob storage|`references/storage.md`|Managing blobs|
|Integrations|`references/integrations.md`|Managing connected services|
|Missing CLI surface, API, webhooks|`references/advanced.md`|Falling back to `vercel api`|
|Node backends|`references/node-backends.md`|Deploying Express/Hono/etc.|
|Monorepos|`references/monorepos.md`|Repo has workspaces or multiple projects|
|Bun runtime|`references/bun.md`|Deploying with Bun|
|Feature flags|`references/flags.md`|Managing flags|
|Global flags|`references/global-options.md`|Exact global options are needed|
|First setup|`references/getting-started.md`|Login/link is incomplete|
|Command workflow|`command/vercel.md`|Running the packaged command surface|

## Environment

- Tracked template: `.env.example`
- Primary non-interactive auth var: `VERCEL_TOKEN`
- NEVER infer missing auth solely because `VERCEL_TOKEN` is unset in the parent shell; existing `vercel login` state may be valid. Verify actual auth with `vercel whoami`. `VERCEL_TOKEN` is mainly for unattended/CI flows.
- CLI does not auto-load `.env`; use direnv or CI secret injection for unattended auth.

## Anti-patterns

- Multiple-project monorepo: `vercel link` creates `project.json`, tracking one project; explicitly use `vercel link --repo`. Check `.vercel/` first when things break.
- Monorepo without `.vercel/`: commands may implicitly run `vercel link` and create the potentially wrong `project.json`; explicitly run `vercel link` or `vercel link --repo` first.
- Wrong team: check with `vercel whoami`; switch with `vercel teams switch`.
- CI: `--yes` required to skip interactive prompts.
- After `vercel build`, `vercel deploy` ignores build output unless run with `--prebuilt`.
- Tokens: use `VERCEL_TOKEN`, not `--token`.
- Preview deploy access: use `vercel curl`, not deployment-protection disabling.
