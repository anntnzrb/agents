# Flake Parts

Clan + flake-parts setup: 3 steps — add inputs; import Clan’s module; define clan and machines.

## 1. Add inputs

Add `flake-parts` to `flake.nix` and wire it to `clan-core`:

```nix [flake.nix]
inputs = {
  nixpkgs.url = "github:NixOS/nixpkgs?ref=nixos-unstable";

  flake-parts.url = "github:hercules-ci/flake-parts";
  flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";

  clan-core = {
    url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
    inputs.nixpkgs.follows = "nixpkgs";
    inputs.flake-parts.follows = "flake-parts";
  };
};
```

`clan-core`’s two `follows` entries reuse your `nixpkgs` and `flake-parts`; omitting them creates duplicate inputs in `flake.lock`. Diagnose/clean up with [Nixpkgs Flake Input](nixpkgs-flake-input/index.md).

:::admonition[Note]{type=note}
To track the exact `nixpkgs` tested by Clan’s CI, use `nixpkgs.follows = "clan-core/nixpkgs"` instead; see the [Nixpkgs Flake Input guide](nixpkgs-flake-input/index.md) for the trade-off.
:::

## 2. Import Clan’s flake-parts module

Inside `mkFlake`, import Clan’s module to expose its [options](https://clan.lol/docs/26.05/reference/options/clan):

```nix
{
  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [
        inputs.clan-core.flakeModules.default
      ];
    };
}
```

This exposes the `clan` option; put the next configuration under `clan`.

## 3. Configure clan and machines

Define clan metadata and at least one machine:

```nix [flake.nix]
{
  outputs =
    inputs@{ flake-parts, clan-core, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
      ];

      imports = [
        clan-core.flakeModules.default
      ];

      clan = {
        meta.name = "my-clan";
        meta.domain = "my-clan.lol";

        machines = {
          jon = {
            imports = [
              ./modules/firefox.nix
            ];

            nixpkgs.hostPlatform = "x86_64-linux";

            clan.core.networking.targetHost = "root@jon";

            disko.devices.disk.main = {
              device = "/dev/disk/by-id/nvme-eui.e8238fa6bf530001001b448b4aec2929";
            };
          };
        };
      };
    };
}
```

- `systems`: flake-parts option listing host platforms for `perSystem` outputs. Add `"aarch64-linux"` or a Darwin system as needed.
- `clan.meta.name` and `clan.meta.domain`: required clan identifiers; each must be unique across managed clans.
- `clan.machines` entries: NixOS configurations. `imports` loads your NixOS modules; `nixpkgs.hostPlatform` sets target architecture; `clan.core.networking.targetHost` sets Clan’s SSH destination for `clan machines update jon` and `clan ssh jon`.
- `disko.devices.disk.main.device`: installation disk. Use a stable `/dev/disk/by-id/...` path so it does not change between boots.

Full option list: [module source](https://git.clan.lol/clan/clan-core/src/branch/26.05/flakeModules/clan.nix).
