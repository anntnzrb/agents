# Nixpkgs Flake Input

`nixpkgs` required; its version determines available packages and whether Clan CI tests the combination.

## Choose a nixpkgs version

Two options; use Option 1 unless you have a reason not to.

### Option 1: Follow clan-core (recommended)

Use the `nixpkgs` version tested by Clan CI:

```nix
inputs = {
  clan-core.url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
  nixpkgs.follows = "clan-core/nixpkgs";
};
```

This uses the same `nixpkgs` revision as `clan-core`; each `clan-core` update brings a matching, end-to-end-verified `nixpkgs`. New upstream packages wait for a `clan-core` input bump.

### Option 2: Track your own nixpkgs

Pin `nixpkgs` and make `clan-core` follow it:

```nix
inputs = {
  nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  clan-core.url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
  clan-core.inputs.nixpkgs.follows = "nixpkgs";
};
```

This provides upstream changes sooner, but the combination is not covered by Clan CI. Use it when you need a package or fix absent from the version followed by `clan-core`.

## Check for duplicate nixpkgs entries

A transitive input can pull its own `nixpkgs` despite correct `follows`; multiple `nixpkgs` entries in `flake.lock` duplicate package-tree evaluation.

Inspect `flake.lock`; two entries like these indicate a duplicate:

```json
"nixpkgs": {
  "locked": {
    "rev": "08b8f92ac6354983f5382124fef6006cade4a1c1",
    "type": "tarball",
    "url": "https://releases.nixos.org/nixpkgs/nixpkgs-25.11pre862603.08b8f92ac635/nixexprs.tar.xz"
  }
},
"nixpkgs_2": {
  "locked": {
    "owner": "nixos",
    "repo": "nixpkgs",
    "rev": "b2a3852bd078e68dd2b3dfa8c00c67af1f0a7d20",
    "type": "github"
  },
  "original": {
    "owner": "nixos",
    "ref": "nixos-25.05",
    "repo": "nixpkgs",
    "type": "github"
  }
}
```

The second entry came from another input. Search `flake.lock` for `nixpkgs_2` to identify it; for example:

```json
"home-manager": {
  "inputs": {
    "nixpkgs": "nixpkgs_2"
  }
}
```

Here, `home-manager` is responsible. Add this to `flake.nix`:

```nix
home-manager.inputs.nixpkgs.follows = "nixpkgs";
```

Repeat for remaining `nixpkgs_3`, `nixpkgs_4`, etc. until `flake.lock` contains one `nixpkgs` entry.

:::admonition[Tip]{type=tip}
Run `nix flake update` after adding a `follows` line so the lockfile picks up the change.
:::

## Customise packages with overlays

Patch an existing `nixpkgs` package with an [overlay](https://wiki.nixos.org/wiki/Overlays); add a new package via the [Clan templates](https://git.clan.lol/clan/clan-core/src/branch/26.05/templates) instead.

This `flake.nix` wires overlays into Clan's `pkgs`:

```nix [flake.nix]
{
  inputs.clan-core.url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
  inputs.nixpkgs.follows = "clan-core/nixpkgs";
  inputs.flake-parts.url = "github:hercules-ci/flake-parts";
  inputs.flake-parts.inputs.nixpkgs-lib.follows = "clan-core/nixpkgs";

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      imports = [
        inputs.clan-core.flakeModules.default
      ];

      clan = {
        imports = [ ./clan.nix ];
      };

      perSystem =
        { system, ... }:
        {
          _module.args.pkgs = import inputs.nixpkgs {
            inherit system;
            overlays = [
              inputs.foo.overlays.default
              (final: prev: {
                # ... things you need to patch ...
              })
            ];
            config.allowUnfree = true;
          };
        };
    };
}
```

`perSystem` imports `nixpkgs` with overlays, then exposes the custom package set through `_module.args.pkgs`; every Clan module in the flake sees it. The first overlay comes from `inputs.foo`; the second is an inline package override. Set `config.allowUnfree = true` for non-free packages. More examples: [Clan templates](https://git.clan.lol/clan/clan-core/src/branch/26.05/templates).
