# Install Nix and direnv

Clan’s CLI, templates, and machine configurations are fetched/evaluated through [Nix](https://nixos.org/); Nix required on every setup machine. [direnv](https://direnv.net/) optional for Clan use, required for Clan development because it loads the repository devshell on `cd`.

NixOS users skip Nix installation; all other instructions apply.

## Install Nix

Use the official installer:

```bash
curl --proto '=https' --tlsv1.2 -sSf -L https://artifacts.nixos.org/nix-installer | sh -s -- install --enable-flakes
```

It sets up `/nix`, configures the daemon, and enables Clan’s required experimental features, `nix-command` and `flakes`; `--enable-flakes` skips the installer prompt. Open a new shell and verify:

```bash
nix --version
```

A version string confirms success. If the command is not found, restart the terminal to update `PATH`.

:::admonition[Already on NixOS?]{type=tip}
NixOS ships with Nix; skip this section. Ensure `experimental-features = nix-command flakes` is in `nix.conf` or `nix.settings.experimental-features` in the NixOS configuration.
:::

## Install direnv

direnv loads and unloads the environment for the current directory’s `.envrc`; Clan devshells use `.envrc`.

```bash
nix profile add nixpkgs#nix-direnv nixpkgs#direnv
```

`nix-direnv` caches Nix devshells, rebuilding them only when inputs change.

Hook direnv into your shell ([instructions](https://direnv.net/docs/hook.html)); this handles bash and zsh:

```bash
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc && echo 'eval "$(direnv hook bash)"' >> ~/.bashrc && eval "$SHELL"
```

The final `eval "$SHELL"` restarts the shell, activating the hook immediately.

On first entry to each directory containing `.envrc`, approve it once:

```bash
direnv: error .envrc is blocked. Run `direnv allow` to approve its content
```

Run `direnv allow` in that directory. Repeat when `.envrc` changes.

## Next steps

With Nix installed, follow [Quick Start](quick-start.md) or a full install guide. Contributors should continue with the [Contributing guide](../guides/contributing/CONTRIBUTING.md), which uses direnv for the development environment.
