# Networking

## Machine connections

Clan networking provides automatic fallback. `clan ssh` and `clan machines update` try configured networks by priority until one succeeds:

1. Direct internet, if configured
2. VPNs such as ZeroTier or Tailscale
3. Tor hidden services
4. Other configured networks

A failed network triggers the next attempt.

### Automatic networking

Public IPs or DNS names: configure direct SSH with the `internet` service; fallback remains available.

```nix [flake.nix] {7-10,14-16}
{
  outputs =
    { self, clan-core, ... }:
    let
      clan = clan-core.lib.clan {
        inventory.instances = {
          # Direct SSH with fallback support
          internet = {
            roles.default.machines.server1 = {
              settings.host = "server1.example.com";
            };
            roles.default.machines.server2 = {
              settings.host = "192.168.XXX.XXX";
            };
          };

          # Fallback: Secure connections via Tor
          tor = {
            roles.server.tags = [ "nixos" ];
          };
        };
      };
    in
    {
      inherit (clan.config) nixosConfigurations;
    };
}
```

Multiple networks are tried in declared priority order; this example uses internet, ZeroTier, then Tor:

```nix [flake.nix] {7-10,13-16,19-21}
{
  outputs =
    { self, clan-core, ... }:
    let
      clan = clan-core.lib.clan {
        inventory.instances = {
          # Priority 1: Try direct connection first
          internet = {
            roles.default.machines.publicserver = {
              settings.host = "public.example.com";
            };
          };

          # Priority 2: VPN for internal machines
          zerotier = {
            roles.controller.machines."controller" = { };
            roles.peer.tags = [ "nixos" ];
          };

          # Priority 3: Tor as universal fallback
          tor = {
            roles.server.tags = [ "nixos" ];
          };
        };
      };
    in
    {
      inherit (clan.config) nixosConfigurations;
    };
}
```

```bash
# View all configured networks and their status
clan network list

# Test connectivity through all networks
clan network ping machine1

# Show complete network topology
clan network overview
```

### Manual `targetHost`

:::admonition[Warning]{type=warning}
Setting `targetHost` directly **disables all automatic networking and fallback**. Use it only for complete control without Clan's connection management.
:::

Inventory-level `deploy.targetHost` is evaluated immediately and is for static addresses independent of NixOS configuration:

```nix [flake.nix] {8}
{
  outputs =
    { self, clan-core, ... }:
    let
      clan = clan-core.lib.clan {
        inventory.machines.server = {
          # WARNING: This bypasses all networking modules!
          # Use for: Static IPs, DNS names, known hostnames
          deploy.targetHost = "root@192.168.XXX.XXX";
        };
      };
    in
    {
      inherit (clan.config) nixosConfigurations;
    };
}
```

Use inventory-level for static IPs (`"root@192.168.XXX.XXX"`), DNS names (`"user@server.example.com"`), or any unchanged address.

Machine-level `clan.core.networking.targetHost` is evaluated after NixOS configuration and can interpolate `config.*` values:

```nix [flake.nix] {7}
{
  outputs =
    { self, clan-core, ... }:
    let
      clan = clan-core.lib.clan {
        machines.server =
          { config, ... }:
          {
            # WARNING: This also bypasses all networking modules!
            # REQUIRED for: Addresses that depend on NixOS config
            clan.core.networking.targetHost = "root@${config.networking.hostName}.local";
          };
      };
    in
    {
      inherit (clan.config) nixosConfigurations;
    };
}
```

Use machine-level for addresses derived from `config.networking.hostName`, multiple config values, or any evaluated NixOS configuration.

:::admonition[Key Difference]{type=info}
**Inventory-level** (`deploy.targetHost`) is evaluated immediately and works with static strings.
**Machine-level** (`clan.core.networking.targetHost`) is evaluated after NixOS configuration and can access `config.*` values.
:::

### Selection

|Scenario|Approach|Reason|
|---|---|---|
|Public servers|`internet` service|Fallback retained|
|Mixed infrastructure|Multiple networks|Automatic failover|
|Machines behind NAT|ZeroTier/Tor|NAT traversal with fallback|
|Testing/debugging|Manual `targetHost`|Full control, no automatic management|
|Single static machine|Manual `targetHost`|Simple|

### `--target-host`

`--target-host` bypasses **ALL networking configuration**:

```bash
# Emergency access - ignores all networking config
clan machines update server --target-host root@backup-ip.com

# Direct SSH - no fallback attempted
clan ssh laptop --target-host user@10.0.0.5
```

Use it for debugging or emergency access when automatic networking fails.
