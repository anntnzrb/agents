# ZeroTier migration: <=25.11 → >=26.05 multi-instance

## Before migration

- Upgrade one non-critical machine first: loss of connectivity must not lock you out; ensure SSH fallback does **not** use ZeroTier.
- If the network worked before the upgrade, do **not** rewrite the inventory. Only make applicable edits in [Required config updates](#required-config-updates-if-you-referenced-the-old-generator).

## Multi-instance change

A machine may join several ZeroTier networks. Each network is one `inventory.instances.<name>` entry with `module.name = "zerotier"`; previously, a clan effectively supported one network and multiple instances were not natively possible.

:::admonition[Do not rename your instances]{type=warning}
Renaming a ZeroTier instance creates a new, disconnected network. Keep existing instance names. If renaming is wanted, do it **before** migration runs.
:::

## Migration

1. Bump `clan-core` in `flake.nix`, then update the lock: `nix flake update clan-core`.
2. Run `clan vars generate`. Before evaluating any generator, clan automatically performs a value-preserving migration that **moves** existing ZeroTier vars into the new layout. It does not regenerate them: identities, network IDs, and IPs remain unchanged. The migration tolerates an interrupted prior run. `vars/` should show only file moves.
3. Verify every machine retained its IP and network ID, for example:

    ```bash
    clan vars get <machine> zerotier-ip-<machine>-<instance>/ip
    clan vars get <controller> zerotier-network-<instance>/network-id
    ```

4. Deploy one test machine, confirm ZeroTier connectivity, then deploy the remainder.

## Required config updates if you referenced the old generator

The old `zerotier` generator no longer exists. Update code referencing `clan.core.vars.generators.zerotier`.

### `targetHost`

Old form:

```nix
clan.core.networking.targetHost =
  "root@[${config.clan.core.vars.generators.zerotier.files.zerotier-ip.value}]";
```

Prefer removing this manual setting: the networking module now handles it. If retained, use:

```nix
clan.core.networking.targetHost =
  "root@[${config.clan.core.vars.generators."zerotier-ip-<machine>-<instance>".files.ip.value}]";
```

For a NixOS module usable on any machine:

```nix
{ config, ... }:
let
  # Auto-derived; no need to hardcode the machine name.
  machineName = config.clan.core.settings.machine.name;
  # Your inventory.instances.<name> key (e.g. "net-a"). Not the module name.
  instanceName = "<instance>";
  ztIp = config.clan.core.vars.generators."zerotier-ip-${machineName}-${instanceName}".files.ip.value;
in
{
  environment.etc."zerotier-ip".text = ztIp;
}
```

## Manual peer authorization → `allowedIds`

For external devices authorized with `zerotier-members allow <node-id>`, move their node IDs into controller settings and delete the tool call:

```nix
roles.controller.machines."<controller>".settings.allowedIds = [
  "deadbeef00" # node ID from `zerotier-cli info` on the external device
];
```

- Prefer `allowedIds`: node IDs are stable per device.
- `allowedIps` remains supported for ZeroTier-IP authorization, but the IP depends on the network.

Problems: contact [matrix](https://matrix.to/#/#clan:clan.lol).
