# Debugging Clan CLI

## Development branch
Suggested: don't install `clan-cli`; clone `clan-core`, add `clan-core/pkgs/clan-cli/bin` to `PATH`, and use the checkout.

:::admonition[Note]{type=note}
After cloning, run `direnv allow` in `clan-core/pkgs/clan-cli` to activate the devshell. This creates a nixpkgs symlink at a specific location; without it, `clan-cli` won't work correctly.
:::

Use [breakpoint()](https://docs.python.org/3/library/pdb.html) to inspect application state. `clan-cli` requires only Python; it has no other dependencies.

```nix
pkgs.mkShell {
  packages = [
    pkgs.python3
  ];
  shellHook = ''
    export GIT_ROOT="$(git rev-parse --show-toplevel)"
    export PATH=$PATH:~/Projects/clan-core/pkgs/clan-cli/bin
  '';
}
```

## Debugging nixos-anywhere
For bugs in complex scripts such as `nixos-anywhere`, replace the command with a local project checkout; see [contribution](CONTRIBUTING.md) for an example.

## `--debug`
Add `--debug` to any `clan` command to print every subprocess command in readable form and its triggering source-code position.

```bash
$ clan machines list --debug
Debug log activated
nix \
    --extra-experimental-features 'nix-command flakes' \
    eval \
    --show-trace --json \
    --print-build-logs '/home/qubasa/Projects/qubasas-clan#clanInternals.machines.x86_64-linux' \
    --apply builtins.attrNames \
    --json
Caller: ~/Projects/clan-core/pkgs/clan-cli/clan_cli/machines/list.py:96::list_nixos_machines

warning: Git tree '/home/qubasa/Projects/qubasas-clan' is dirty
demo
gchq-local
wintux

```

## VS Code
Source paths printed in the integrated terminal are clickable. Open the Clan in VS Code, run (for example) `clan machines list --debug`, then Ctrl-click (Cmd-click on macOS) the subprocess caller path and add `breakpoint()` there to inspect state.

## Print-message tracing
- `TRACE_PRINT=1`: add each print's source location; with `--debug`, every print shows its code trigger.

    ```bash
    export TRACE_PRINT=1
    ```

- `TRACE_DEPTH=N`: show a deeper stack trace with N frames (for example, 3).

    ```bash
    export TRACE_DEPTH=3
    ```

### Additional debug logging
- `CLAN_DEBUG_NIX_SELECTORS=1`: verbose `flake.select` logs
- `CLAN_DEBUG_NIX_PREFETCH=1`: verbose `flake.prefetch` logs
- `CLAN_DEBUG_COMMANDS=1`: print the diffed environment of executed commands
- `CLAN_NO_SELECT_DISK_CACHE=1`: disable the on-disk select cache; use only the in-memory cache

```bash
export CLAN_DEBUG_NIX_SELECTORS=1
export CLAN_DEBUG_NIX_PREFETCH=1
export CLAN_DEBUG_COMMANDS=1
```

Use these options to locate the source and context of print messages and debug logs.

## Performance
Set `CLAN_CLI_PERF=1`; after a Clan command, receive a summary of performance metrics.

## Packages and tests
`nix flake show` lists packages and tests. `checks` contains CI tests; `packages` contains projects.

```console
git+file:///home/lhebendanz/Projects/clan-core
├───checks
│   └───x86_64-linux
│       ├───borgbackup omitted (use '--all-systems' to show)
│       ├───check-for-breakpoints omitted (use '--all-systems' to show)
│       ├───clan-dep-age omitted (use '--all-systems' to show)
│       ├───clan-dep-bash omitted (use '--all-systems' to show)
│       ├───clan-dep-e2fsprogs omitted (use '--all-systems' to show)
│       ├───clan-dep-fakeroot omitted (use '--all-systems' to show)
│       ├───clan-dep-git omitted (use '--all-systems' to show)
│       ├───clan-dep-nix omitted (use '--all-systems' to show)
│       ├───clan-dep-openssh omitted (use '--all-systems' to show)
│       ├───"clan-dep-python3.11-mypy" omitted (use '--all-systems' to show)
├───packages
│   └───x86_64-linux
│       ├───clan-cli omitted (use '--all-systems' to show)
│       ├───clan-cli-docs omitted (use '--all-systems' to show)
│       ├───clan-ts-api omitted (use '--all-systems' to show)
│       ├───clan-app omitted (use '--all-systems' to show)
│       ├───default omitted (use '--all-systems' to show)
│       ├───docs omitted (use '--all-systems' to show)
│       ├───editor omitted (use '--all-systems' to show)
└───templates
    ├───default: template: Initialize a new clan flake
    └───default: template: Initialize a new clan flake
```

Run an individual test via its tree path, for example:

```bash
nix run .#checks.x86_64-linux.clan-pytest -L
```

## Devshell tests with breakpoints
```bash
cd ./pkgs/clan-cli
pytest -n0 -s --maxfail=1 ./tests/test_nameofthetest.py
```

Put `breakpoint()` in Python code where execution should pause.

## Nix-sandbox tests
```bash
nix build .#checks.x86_64-linux.clan-pytest-with-core
```

```bash
nix build .#checks.x86_64-linux.clan-pytest-without-core
```

### Inspect the Nix sandbox
Insert an endless sleep where execution should pause:

```python
import time
time.sleep(3600)  # Sleep for one hour
```

Find and attach to the sandbox:

```bash
psgrep $PROCESS_NAME
cntr attach $CONTAINER_ID
```

Alternatively, use the [Nix breakpoint hook](https://nixos.org/manual/nixpkgs/stable/#breakpointhook).
