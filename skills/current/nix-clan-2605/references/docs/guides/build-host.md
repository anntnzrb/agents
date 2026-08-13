# Build Host

`deploy.buildHost`: run `nix build` on a separate machine; target host only receives the finished system closure and activates it.

:::admonition[Do I need this?]{type=note}
Set `buildHost` only when the target is a poor builder (low RAM, slow CPU, flaky network, or no access to a substituter available to the builder). Otherwise leave it unset.
:::

## Background

Default `clan machines update <machine>` evaluates the flake on the workstation, then builds and activates on `deploy.targetHost`. With `deploy.buildHost`, evaluation remains local; the builder builds, then copies the closure to the target over a second SSH connection for activation.

Typical reasons: resource-constrained target (Raspberry Pi, small VPS); builder has better access to a substituter/private cache; keep build load off production. Private flake inputs are not a reason: evaluation fetches them locally, so the builder need not reach the private repositories. See [Private Flake Inputs](private-inputs.md).

:::admonition[Architectures Must Match]{type=warning}
`nix build` compiles natively for the build host. A target `aarch64-linux` with an `x86_64-linux` builder produces the wrong closure. Match architectures or arrange cross-compilation.
:::

## 1. Set It in the Inventory

Add `deploy.buildHost` beside `deploy.targetHost` in `clan.nix`:

```text {.nix title="clan.nix"}
inventory.machines.my-machine = {
  deploy.targetHost = "root@target.example.com";
  deploy.buildHost  = "root@builder.example.com";
};
```

Same format as `targetHost`:

```text
user@host:port?SSH_OPTION=SSH_VALUE&SSH_OPTION_2=VALUE_2
```

Examples:

- `root@builder.example.com`
- `builder.example.com:2222`
- `root@builder.example.com:22?IdentityFile=/path/to/key`

## 2. Or Set It in the Machine Configuration

Set `buildHost` in the machine's NixOS configuration when deployment topology belongs there:

```text {.nix title="machines/my-machine/configuration.nix"}
clan.core.networking.buildHost = "root@builder.example.com";
```

Prefer inventory when possible: it keeps all machine topology visible together.

## 3. Or Override from the CLI

```bash
clan machines update my-machine --build-host root@builder.example.com
```

Force a local build, including when inventory specifies a remote builder:

```bash
clan machines update my-machine --build-host localhost
```

:::admonition[Resolution Order]{type=note}
`buildHost` precedence, highest first:

1. `--build-host` command-line option
2. `inventory.machines.<name>.deploy.buildHost`
3. `clan.core.networking.buildHost` in machine configuration
4. Default: `deploy.targetHost` (build on target)
:::

## What Happens During a Deploy

With `buildHost`, `clan machines update`:

1. Workstation evaluates the flake and uploads its source to the builder.
2. Builder runs `nix build` and produces the system closure.
3. Builder runs `nix copy` over SSH to the target; Clan activates the new system there.

The builder opens the second SSH connection with its own credentials and `~/.ssh/known_hosts`, independent of the workstation session. By default it has neither:

- A private key accepted by the target for the user in `deploy.targetHost`.
- The target's `known_hosts` entry.

## Authenticating the Second Hop

Options:

1. Install a dedicated SSH key on the builder and authorize it on the target (recommended).
2. Forward the local SSH agent through the builder (quicker, riskier to leave running).

Setup, tradeoffs, and option 1 steps: [SSH Agent Forwarding](ssh-agent-forwarding.md). Do this once per builder.

## First Deploy: Host Key Verification

If the target key is absent from the builder's `known_hosts`, nested SSH fails:

```text
Host key verification failed.
error: failed to start SSH connection to '<target-host>'
```

On the first run, use `--host-key-check accept-new`; Clan forwards it to nested SSH and records the target key:

```bash
clan machines update my-machine --host-key-check accept-new
```

Drop the flag subsequently. See [Host Key Verification](ssh-agent-forwarding.md#host-key-verification) for the mechanism and `ssh-keyscan` alternative.

## Using `nixos-rebuild` Directly

When bypassing `clan machines update`, use `nixos-rebuild --build-host`:

```bash
nixos-rebuild switch \
  --flake .#my-machine \
  --target-host root@target.example.com \
  --build-host  root@builder.example.com
```

If using Clan vars, first run `clan vars upload my-machine`. See [NixOS Rebuild](nixos-rebuild.md).

## Troubleshooting

### Permission Denied During Closure Copy

`Permission denied (publickey)` during builder-to-target closure copy means the builder lacks an accepted target key. Follow [SSH Agent Forwarding](ssh-agent-forwarding.md) to install a dedicated builder key.

### Host Key Verification Fails After the Build Succeeds

`Host key verification failed` after a successful build means the builder lacks the target's `known_hosts` entry. Re-run with `--host-key-check accept-new` or seed it manually; see [Host Key Verification](ssh-agent-forwarding.md#host-key-verification).

### The Build Runs on the Target, Not the Builder

Check, in order: passed `--build-host`; `clan.nix` inventory entry; `clan.core.networking.buildHost`. If none is set, fallback to `targetHost` is intentional.

### Architecture Mismatch Between Build Host and Target

An error like `a 'x86_64-linux' ... is required to build ..., but I am a 'aarch64-linux'` indicates differing architectures. Match them or build locally with `--build-host localhost`.

## Related

- [SSH Agent Forwarding](ssh-agent-forwarding.md) — second-hop authentication.
- [Private Flake Inputs](private-inputs.md) — private Git flake inputs without shipping credentials to the builder.
- [NixOS Rebuild](nixos-rebuild.md) — direct `nixos-rebuild` instead of `clan machines update`.
