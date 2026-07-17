---
name: vercel-cli
description: Deploy, manage, and debug Vercel projects, environments, domains, logs, integrations, and CI/CD.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Vercel CLI Skill

The Vercel CLI (`vercel` or `vc`) deploys, manages, and develops projects on the Vercel platform from the command line. Use `vercel <command> -h` for full flag details on any command.

## Critical: Project Linking

Set `<VERCEL_CMD>` to installed `vercel`, or to `bun x vercel` for ephemeral
execution. Examples use `vercel` for readability.

Commands must be run from the directory containing the `.vercel` folder (or a subdirectory of it). How `.vercel` gets set up depends on your project structure:

- **`.vercel/project.json`**: Created by `vercel link`. Links a single project. Fine for single-project repos, and can work in monorepos if there's only one project.
- **`.vercel/repo.json`**: Created by `vercel link --repo`. Links a repo that may contain multiple projects. Always a good idea when any project has a non-root directory (e.g., `apps/web`).

Running from a project subdirectory (e.g., `apps/web/`) skips the "which project?" prompt since it's unambiguous.

**When something goes wrong, check how things are linked first** — look at what's in `.vercel/` and whether it's `project.json` or `repo.json`. Also verify you're on the right team with `vercel whoami` — linking while on the wrong team is a common mistake.

## Quick Start

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

| Need | Read | When |
| --- | --- | --- |
| Deployment | `references/deployment.md` | Deploying or promoting |
| Local development | `references/local-development.md` | Running locally |
| Environment variables | `references/environment-variables.md` | Reading or changing env |
| CI/CD | `references/ci-automation.md` | Automating deployment |
| Domains/DNS | `references/domains-and-dns.md` | Changing domain state |
| Projects/teams | `references/projects-and-teams.md` | Linking or scoping |
| Logs, debugging, protected previews | `references/monitoring-and-debugging.md` | Diagnosing or using `vercel curl` |
| Blob storage | `references/storage.md` | Managing blobs |
| Integrations | `references/integrations.md` | Managing connected services |
| Missing CLI surface, API, webhooks | `references/advanced.md` | Falling back to `vercel api` |
| Node backends | `references/node-backends.md` | Deploying Express/Hono/etc. |
| Monorepos | `references/monorepos.md` | Repo has workspaces or multiple projects |
| Bun runtime | `references/bun.md` | Deploying with Bun |
| Feature flags | `references/flags.md` | Managing flags |
| Global flags | `references/global-options.md` | Exact global options are needed |
| First setup | `references/getting-started.md` | Login/link is incomplete |
| Command workflow | `command/vercel.md` | Running the packaged command surface |

## Environment

- Tracked template: `.env.example`
- Primary non-interactive auth var: `VERCEL_TOKEN`
- Do not infer missing auth from `VERCEL_TOKEN` being unset in the parent shell; existing `vercel login` state may already be valid. Use `vercel whoami` to verify real auth state. `VERCEL_TOKEN` is mainly for unattended/CI flows.
- The CLI does not auto-load `.env`; use direnv or CI secret injection for unattended auth.

## Anti-Patterns

- **Wrong link type in monorepos with multiple projects**: `vercel link` creates `project.json`, which only tracks one project. Use `vercel link --repo` instead. When things break, check `.vercel/` first.
- **Letting commands auto-link in monorepos**: Many commands implicitly run `vercel link` if `.vercel/` doesn't exist. This creates `project.json`, which may be wrong. Run `vercel link` (or `--repo`) explicitly first.
- **Linking while on the wrong team**: Use `vercel whoami` to check, `vercel teams switch` to change.
- **Forgetting `--yes` in CI**: Required to skip interactive prompts.
- **Using `vercel deploy` after `vercel build` without `--prebuilt`**: The build output is ignored.
- **Hardcoding tokens in flags**: Use `VERCEL_TOKEN` env var instead of `--token`.
- **Disabling deployment protection**: Use `vercel curl` instead to access preview deploys.
