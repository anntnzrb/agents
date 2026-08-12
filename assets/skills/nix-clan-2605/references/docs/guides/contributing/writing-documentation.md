# Writing Documentation

Docs source: `docs/src/`. SvelteKit site: `pkgs/clan-site`, which reads and renders the Markdown. Before writing prose, read [styleguide.md](styleguide.md): source of truth for headings, admonitions, code blocks, capitalization, and tone.

:::admonition[Prerequisites]{type=note}
Working Clan checkout; Nix and direnv installed. If setup is incomplete, see [Contributing](CONTRIBUTING.md).
:::

## 1. Start the dev server

From the repository, enter `docs/` and activate its devshell:

```bash
cd clan-core/docs
direnv allow
```

`docs/.envrc` loads `.#docs`; its shell hook changes to `pkgs/clan-site`, sets `CLAN_SITE_DIR` to that path, copies generated site assets, and puts required tools on `PATH`.

:::admonition[Where is my shell?]{type=tip}
`direnv allow` intentionally changes the working directory to `pkgs/clan-site`; Markdown remains in `docs/src/`, which the dev server reads.
:::

Start Vite with hot module reloading:

```bash
clan-site
```

`clan-site` = `clan-site dev`: serves a terminal-printed local URL, watches `docs/src/`, and updates the browser in a second or two without a full reload. Open a new browser tab automatically:

```bash
clan-site dev -b
```

## 2. Find the file

Pages live under `docs/src/`:

- `docs/src/getting-started/` — install and quick-start guides.
- `docs/src/guides/` — longer how-to pages, grouped by topic (`inventory/`, `services/`, `vars/`, and so on).
- `docs/src/reference/` — generated CLI and option references; NEVER edit generated files manually.
- `docs/src/concepts/`, `docs/src/decisions/` — conceptual explainers and architecture decision records.

A page is either one Markdown file (`flake-parts.md`) or a directory containing `index.md` (`nixpkgs-flake-input/index.md`). Use a directory for images or sub-pages shipped with the page.

## 3. Register pages in navigation

Add new pages to the hand-maintained `docsNav` tree in `pkgs/clan-site/clan-site.config.ts`; otherwise they render but do not appear in the sidebar. Paths are relative to `docs/src/` and omit `.md`:

```ts
{
  label: "Guides",
  children: [
    "guides/flake-parts",
    "guides/writing-documentation",
  ],
},
```

Nested groups use `label` / `children`:

```ts
{
  label: "Contributing",
  children: [
    "guides/contributing/CONTRIBUTING",
    "guides/contributing/writing-documentation",
    "guides/contributing/styleguide",
  ],
},
```

Changes to `clan-site.config.ts` hot-reload, so tree rearrangements appear immediately.

## 4. Use framework features

Clan docs extend CommonMark; see [styleguide.md](styleguide.md) for the full catalogue. Common features:

Admonitions:

```md
:::admonition[Prerequisites]{type=note}
Nix installed, SSH key in place.
:::
```

Filename labels and highlighted lines in code blocks:

````md
```nix [flake.nix] {2,4-6}
{
  this line is highlighted
  this line is not
  this line is highlighted
  this line is highlighted
  this line is highlighted
}
```
````

Cross-links use `/docs/...` and no file extension:

```md
See [Flake Parts](/docs/guides/flake-parts) for the full setup.
```

`{{! version }}` inserts the current Clan version in rendered text, links, or code examples:

````md
```bash
nix run https://clan.lol/install/{{! version }} --refresh -- init
```
````

## 5. Check your work

Before opening a PR, run from the same shell:

```bash
clan-site lint
```

This runs ESLint, Stylelint, and Svelte type checks against `pkgs/clan-site`; it does not validate prose, but catches broken Markdown syntax that reaches rendered HTML.

Build and preview production output:

```bash
clan-site build -s
```

`-s` serves the build for clicking through it; add `-b` to open a browser tab.

## Troubleshooting

- **`direnv` does not activate in `docs/`:** run `direnv allow` once. If the hook was never installed, follow step 2 of [Contributing](CONTRIBUTING.md) and restart the shell.
- **`clan-site` is not found:** re-enter `docs/` for direnv, or run `nix develop .#docs` manually from the repository root.
- **New page absent from sidebar:** add it to `docsNav` under the correct section in `pkgs/clan-site/clan-site.config.ts`.
- **`docs/src/` edits do not reload:** ensure `clan-site` is still running in its terminal. The watcher covers `docs/src/` and the generated docs directory; changes elsewhere do not trigger HMR.
