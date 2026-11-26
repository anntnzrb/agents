# Environment Variables

## Scoping

Env vars are scoped to **environments**: production, preview, and development. Preview variables can also be scoped to a Git branch.

Variables can be sensitive or config. Sensitive values are encrypted and not readable after creation; config values remain readable where the CLI or dashboard exposes them.

## Managing Env Vars

Current Vercel CLI syntax uses `--environment` / `-e`; the environment is not a positional argument. Use `--git-branch` for branch-scoped preview variables.

```bash
vercel env add API_KEY --environment production
vercel env add PREVIEW_TOKEN --environment preview --git-branch feature-x
vercel env add API_URL --environment production,preview,development
vercel env list
vercel env list --environment preview --git-branch feature-x
vercel env update API_KEY --environment production --value "<new-value>" --yes
vercel env remove API_KEY --environment production --confirm-name API_KEY
printf '%s' "<value>" | vercel env add TOKEN --environment production
```

`vercel env add` prompts for omitted environments and values. For non-interactive creation, pass `--environment`, `--value`, and `--yes`, or pipe the value on stdin. Use `--force` only when intentionally replacing an existing variable in the same environment.

`vercel env update` selects one existing variable by environment or branch, but the new value applies to every environment that variable covers. `vercel env remove` removes the variable from every environment it covers unless `--environment` narrows the removal. Agents cannot use `--yes` to approve removal; use `--confirm-name <name>` only after a person approves.

## Pulling Locally

```bash
vercel env pull                             # writes development env to .env.local
vercel env pull .env.development            # writes to a custom file
vercel env pull --environment preview --git-branch feature-x
vercel env pull --deployment dpl_xxx        # pull for one deployment
```

`vercel pull` also downloads env vars along with project config.

## Running with Env Vars

Inject env vars into a subprocess without writing to a file:

```bash
vercel env run -- npm test
vercel env run --environment preview --git-branch feature-x -- npm test
```

The `--` separator is required before the command. `--environment` defaults to development for `env run` and `env pull`.
