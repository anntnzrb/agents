# Mesh VPN

Connect Clan machines over a [ZeroTier VPN](https://zerotier.com): configure one machine as controller, then add machines as peers. Clan machines use a chosen network technology by default. This guide configures `zerotier` through Clan’s `Inventory` system.

```text
Clan
    Node A
    <-> (zerotier / mycelium / ...)
    Node B
```

## Controller

Controller: initial entrypoint for new VPN machines; signs their IDs. Continuous operation is not essential after signing, but choose a machine reachable for updates so new peers can be added.

Guide machines:
- `controller`: ZeroTier controller.
- `new_machine`: machine to add to the VPN.

## Configure the Service

```nix [flake.nix] {19-25}
{
  inputs.clan-core.url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
  inputs.nixpkgs.follows = "clan-core/nixpkgs";

  outputs =
    { self, clan-core, ... }:
    let
      # Sometimes this attribute set is defined in clan.nix
      clan = clan-core.lib.clan {
        inherit self;

        meta.name = "myclan";
        meta.domain = "ccc";

        inventory.machines = {
          controller = { };
          new_machine = { };
        };

        inventory.instances = {
          zerotier = {
            # Assign the controller machine to the role "controller"
            roles.controller.machines."controller" = { };

            # All clan machines are zerotier peers
            roles.peer.tags."all" = { };
          };
        };
      };
    in
    {
      inherit (clan) nixosConfigurations nixosModules clanInternals;
    };
}
```

## Apply the Configuration

Update `controller` first:

```bash
clan machines update controller
```

Then update all other peers:

```bash
clan machines update
```

### Verify Connection

On `new_machine`:

```bash
$ sudo zerotier-cli info
```

Expected status: "ONLINE":

```console
200 info d2c71971db 1.12.1 ONLINE
```

## Further

**ZeroTier** currently is the only mesh-vpn fully integrated into clan. Planned network technologies include tinc and head/tailscale. yggdrassil and mycelium currently work through the Inventory, but are not integrated into the networking module.

ZeroTier was chosen because tests found it straightforward to bootstrap; it supports self-hosting a controller that need not be globally reachable, making it suitable for starting the project.

## Debugging

### Retrieve the ZeroTier ID

In the repo:

```console
$ clan vars list $MACHINE_NAME
```

```console
$ clan vars list controller
zerotier/zerotier-identity-secret: ********
zerotier/zerotier-ip: fd0a:b849:2928:1234:c99:930a:a959:2928
zerotier/zerotier-network-id: 0aa959282834000c
```

On the device:

```bash
$ sudo zerotier-cli info
```

#### Manually Authorize a Machine on the Controller

::::tabs
:::tab[with ZeroTierIP]

  ```bash
  $ sudo zerotier-members allow --member-ip $ZEROTIER_IP
  ```

  `$ZEROTIER_IP`: ZeroTier IP obtained above.
:::
:::tab[with ZeroTierID]

  ```bash
  $ sudo zerotier-members allow $ZEROTIER_ID
  ```

  `$ZEROTIER_ID`: ZeroTier ID obtained above.
:::
::::
