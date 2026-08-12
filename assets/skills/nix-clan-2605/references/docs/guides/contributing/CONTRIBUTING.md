# Contributing

Clan development: Linux, macOS.

:::admonition[How changes get tested]{type=note}
Every pull request runs through Gitea CI; failed checks block the PR until resolved. Local `nix fmt` and the pre-commit hook catch most CI checks before pushing.
:::

## Setup

### 1. Install Nix and direnv

If absent, follow [Install Nix and direnv](../../getting-started/install-nix.md); return when `nix --version` works and direnv is hooked into the shell.

### 2. Fork and clone `clan-core`

Register at [git.clan.lol](https://git.clan.lol), fork [clan-core](https://git.clan.lol/clan/clan-core), clone the fork, then add `upstream` to pull `main` changes:

```bash
git remote add upstream gitea@git.clan.lol:clan/clan-core.git
```

### 3. Activate the devshell

In the area-specific directory, allow its `.envrc`; most CLI work uses `pkgs/clan-cli`:

```bash
cd clan-core/pkgs/clan-cli
direnv allow
```

First approval usually prints:

```bash
direnv: error .envrc is blocked. Run `direnv allow` to approve its content
```

`direnv allow` approves `.envrc` for execution on each entry. The devshell provides `clan`, Python, formatters, test runners, and `clan-cli` checkout symlinks; subsequent directory entry re-enters it automatically.

### 4. Optional pre-commit hook

```bash
./scripts/pre-commit
```

Installs a git hook running `nix fmt` and lint checks on staged files before each commit. Run the formatter manually with:

```bash
nix fmt
```

## Documentation work

Sources: `docs/src/`. Dev server: `pkgs/clan-site`. Follow [Writing Documentation](writing-documentation.md) for hot-reload preview and navigation registration, plus [style guide](styleguide.md).

## Local related-project overrides

Related projects:

- [data-mesher](https://git.clan.lol/clan/data-mesher)
- [nixos-facter](https://github.com/nix-community/nixos-facter)
- [nixos-anywhere](https://github.com/nix-community/nixos-anywhere)
- [disko](https://github.com/nix-community/disko)

For a fix touching one, clone it and replace Clan’s pinned package with your checkout. `clan-cli` example:

```python
run(
    nix_shell(
        ["nixos-anywhere"],
        cmd,
    ),
    RunOpts(log=Log.BOTH, prefix=machine.name, needs_user_terminal=True),
)
```

Replace the package reference with a local path:

```python
run(
    nix_shell(
        ["<path_to_local_src>#nixos-anywhere"],
        cmd,
    ),
    RunOpts(log=Log.BOTH, prefix=machine.name, needs_user_terminal=True),
)
```

`<path_to_local_src>` accepts any valid [flake reference](https://nix.dev/manual/nix/2.26/command-ref/new-cli/nix3-flake.html#flake-references), including a directory, fork branch, or open PR, enabling end-to-end patch testing before merge.

## Backport release fixes

Backport bug or security fixes still relevant to an existing release to its matching branch (for example `25.11`). `scripts/backport-pr` cherry-picks and opens a Gitea PR:

```bash
scripts/backport-pr 25.11 <commit> [<commit>...]
```

It:

- skips commits already on the target or touching only files absent from that release;
- cherry-picks the rest to `backport/<target>/<sha>`;
- pushes the branch and opens a `[<target>] …` PR through `tea`;
- deletes the throwaway branch if nothing applies cleanly.

On conflict, it leaves the backport branch and prints remaining `git` and `tea` commands for manual completion. Preview without changing branches using `-n` / `--dry-run` or `DRY_RUN=1`.

## Coding standards

- New module names: kebab-case.
- `vars` definitions: kebab-case wherever surrounding code allows.
- CLI help strings: initial capital; no final period.

## Documentation style

Docs must follow [style guide](styleguide.md), covering admonition syntax, code-block highlighting, capitalisation, and Clan’s writing principles.
