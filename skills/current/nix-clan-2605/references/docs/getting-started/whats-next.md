# What's Next

First Clan created; machines, users, and services configured; Clan manageable through machine updates.

## Generate Vars

Usually automatic on machine deployment, but required manually beforehand for `nix flake check`. Generate all required variables and secrets:

```bash
clan vars generate
```

## Check Configuration

Validate the configuration:

```bash
nix flake check
```

Checks system configuration for correctness and errors.

:::admonition[Tip]{type=tip}

Integrate `nix flake check` into [Continuous Integration](https://en.wikipedia.org/wiki/Continuous_integration) to merge only valid Nix configurations.
:::

## Backups

Backups recommended now on all machines. Follow the [detailed backup guide](../guides/backups/backup-intro.md) and keep files safe.

## Migrate Existing Devices

[Migrate additional existing systems](../guides/migrations/convert-existing-NixOS-configuration.md) into your Clan using the extended guides.
