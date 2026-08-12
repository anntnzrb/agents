# Convert Existing NixOS Configuration

Convert an existing NixOS flake to a Clan, retaining hosts/configuration and gaining Clan services, inventory, and CLI.

:::admonition[Warning]{type=warning}
Migration can be trickier than starting new and may cause bugs or unexpected issues. Read [Getting Started](../../getting-started/quick-start.md) first. After you have a working setup and understand the concepts, transferring a NixOS configuration is easy.
:::

## Back up

Back up the existing configuration before starting. If using version control, perform the migration in a separate branch until it works as expected.

## Starting point

This guide assumes NixOS flakes. Otherwise, first [migrate to a flake-based setup](https://nix.dev/manual/nix/2.25/command-ref/new-cli/nix3-flake.html). Example hosts: **berlin** and **cologne**.

```nix
{
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs, ... }:
    {

      nixosConfigurations = {

        berlin = nixpkgs.lib.nixosSystem {
          system = "x86_64-linux";
          modules = [ ./machines/berlin/configuration.nix ];
        };

        cologne = nixpkgs.lib.nixosSystem {
          system = "x86_64-linux";
          modules = [ ./machines/cologne/configuration.nix ];
        };
      };
    };
}
```

## 1. Add `clan-core` to `inputs`

```nix
inputs.clan-core = {
  url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
  # Don't do this if your machines are on nixpkgs stable.
  inputs.nixpkgs.follows = "nixpkgs";
}
```

## 2. Update outputs

Add `clan-core` to the output parameters:

```diff
-  outputs = { self, nixpkgs, ... }:
+  outputs = { self, nixpkgs, clan-core }:
```

`clan-core.lib.clan` creates the existing `nixosConfigurations` output and adds `clanInternals`. Use `let...in` to define the Clan and expose its outputs:

```nix
{
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  inputs.clan-core = {
    url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      clan-core,
      ...
    }:
    let
      clan = clan-core.lib.clan {
        self = self; # this needs to point at the repository root
        specialArgs = { };
        meta.name = throw "Change me to something unique";
        meta.domain = throw "Change me to something unique";

        machines = {
          berlin = {
            nixpkgs.hostPlatform = "x86_64-linux";
            imports = [ ./machines/berlin/configuration.nix ];
          };
          cologne = {
            nixpkgs.hostPlatform = "x86_64-linux";
            imports = [ ./machines/cologne/configuration.nix ];
          };
        };
      };
    in
    {
      inherit (clan.config) nixosConfigurations nixosModules clanInternals;
      clan = clan.config;
    };
}
```

Existing Nix tooling continues to work. Run `nix flake show`; verify both hosts remain recognized and the `clan` output appears:

```console
❯ nix flake show
git+file:///my-nixos-config
├───clan: unknown
└───nixosConfigurations
    ├───berlin: NixOS configuration
    └───cologne: NixOS configuration
```

You can also rebuild with `nixos-rebuild` and verify the result.

## 3. Add `clan-cli` to `devShells`

Expose the CLI through a flake `devShell` (recommended); another Nix package-install method is possible, but a development shell keeps the CLI version synchronized with the configuration.

```nix
devShells."x86_64-linux".default = nixpkgs.legacyPackages."x86_64-linux".mkShell {
  packages = [ clan-core.packages."x86_64-linux".clan-cli ];
}
```

Run `nix develop` in the flake directory to enter a shell containing `clan`. Because it is used for every Clan interaction, [direnv](https://direnv.net/) is recommended. Verify it with `clan machines list`:

```console
❯ nix develop
[user@host:~/my-nixos-config]$ clan machines list
berlin
cologne
```

## Specify targets

Clan needs reachable host addresses. For testing, set `clan.core.networking.targetHost` to each machine's address or hostname:

```nix
# machines/berlin/configuration.nix
{
  clan.core.networking.targetHost = "123.4.56.78";
}
```

See [configuring machine networking](../networking/networking.md).

## Next steps

The setup is complete. Use the CLI to manage hosts or configure services; for example, deploy with `clan machines update berlin`.
