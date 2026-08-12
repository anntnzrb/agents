# Introduction to Clan Services

## Services

A service is a pre-built, configurable module for one job. Declare services, target machines, roles, and settings in `clan.nix`; do not hand-write their machine configuration. Clan builds and deploys the resulting configuration. The library covers SSH, WiFi, users, backups, networking, package installation, and more.

Services live under `inventory.instances`:

```nix
inventory.instances = {
  sshd = {
    roles.server.tags = [ "all" ];
  };
};
```

This runs `sshd` with every inventory machine in its `server` role.

## First service and deployment

`packages` installs nixpkgs software:

```nix
inventory.instances = {
  packages = {
    roles.default.machines."sally-laptop" = {
      settings.packages = [ "bat" "htop" "ripgrep" ];
    };
  };
};
```

Save `clan.nix`, then deploy with one command: install a machine initially or update an existing deployment:

```bash
clan machines install sally-laptop
```

```bash
clan machines update sally-laptop
```

Clan builds a NixOS configuration containing the services, uploads it, and runs `nixos-rebuild switch`; no target-side manual configuration is needed.

Services requiring secrets (passwords, encryption keys, network credentials) need secret generation before deployment:

```bash
clan vars generate sally-laptop
clan machines install sally-laptop
```

`clan vars generate` prompts for required secrets and stores them securely. Run it when adding a service or changing its secrets; `packages` does not require it.

Verify the package through Clan SSH:

```bash
clan ssh sally-laptop
bat --version
```

Delete a package from `settings.packages` and run `clan machines update`; the machine then matches `clan.nix` (declarative configuration).

## Roles

A role defines a machine's part in a service. `borgbackup` distinguishes backup senders (`client`) from the storage machine (`server`):

```nix
inventory.instances = {
  borgbackup = {
    roles.client.machines."sally-laptop" = {};
    roles.client.machines."fred-laptop" = {};
    roles.server.machines."backup-server" = {};
  };
};
```

`client` sends backups; `server` receives and stores them. Clan applies role-specific configuration. Services whose machines all perform the same job use the single `default` role; other services define named roles. Service docs list available roles and each role's behavior.

## Tags

Define machine groups in `inventory.machines`:

```nix
inventory.machines = {
  sally-laptop = {
    tags = [ "laptop" ];
  };
  fred-laptop = {
    tags = [ "laptop" ];
  };
  backup-server = {
    tags = [ "server" ];
  };
};
```

Target a tag instead of listing every machine:

```nix
inventory.instances = {
  borgbackup = {
    roles.client.tags = [ "laptop" ];
    roles.server.machines."backup-server" = {};
  };
};
```

Clan resolves a tag to all machines carrying it. Adding `barb-laptop` with `tags = [ "laptop" ]` automatically includes her in this backup role without changing the service declaration.

At least these tags are built in:

|Tag|Matches|
|---|---|
|`all`|Every machine in the inventory|
|`nixos`|Every machine with `machineClass = "nixos"`|
|`darwin`|Every machine with `machineClass = "darwin"`|

Define other tags in each machine's `tags` list. A role may combine tags and explicit machines; Clan unions them:

```nix
inventory.instances = {
  borgbackup = {
    roles.client.tags = [ "laptop" ];
    roles.client.machines."office-desktop" = {};
    roles.server.machines."backup-server" = {};
  };
};
```

## Settings

`settings` may apply role-wide or per machine. Role-wide settings apply to every machine in that role:

```nix
inventory.instances = {
  borgbackup = {
    roles.client.tags = [ "laptop" ];
    roles.client.settings.startAt = "*-*-* 02:00:00";
    roles.server.machines."backup-server" = {};
  };
};
```

Per-machine settings layer over role-wide settings:

```nix
inventory.instances = {
  wifi = {
    roles.default.tags = [ "laptop" ];
    roles.default.settings.networks.home = {};
    roles.default.machines."sally-laptop" = {
      settings.networks.office = {};
    };
    roles.default.machines."fred-laptop" = {};
  };
};
```

Here every laptop gets `home`; Sally additionally gets `office`; Fred gets only `home`.

In Nix, `= {}` declares inclusion or enables a setting with no extra values. For example, `roles.default.machines."fred-laptop" = {}` adds Fred with no customization, while `settings.networks.home = {}` enables `home` with defaults. The attribute's presence declares it; the empty set adds nothing.

## Multiple instances

To configure one service differently for different machines, give each instance a unique name and set `module.name` to the service module:

```nix
inventory.instances = {
  user-sally = {
    module.name = "users";
    roles.default.machines."sally-laptop" = {};
    roles.default.settings.user = "sally";
  };
  user-fred = {
    module.name = "users";
    roles.default.machines."fred-laptop" = {};
    roles.default.settings.user = "fred";
  };
};
```

By default, an instance name is also its service module name. `module.name` selects the module; instance names may be arbitrary but must be unique. Not every service supports multiple instances; check its documentation first.

## Available services

Clan includes 50+ built-in services, including:

|Service|What it does|
|---|---|
|`packages`|Install packages from nixpkgs|
|`sshd`|SSH server with key management|
|`users`|User accounts and passwords|
|`wifi`|WiFi network configuration|
|`borgbackup`|Encrypted backups|
|`syncthing`|Peer-to-peer file sync|
|`wireguard`|VPN networking|
|`zerotier`|Mesh networking|
|`monitoring`|Prometheus + Grafana|
|`matrix-synapse`|Chat server|

Full list: [Services Reference](../../services/definition.md).

## Complete example

```nix
inventory.machines = {
  sally-laptop = {
    tags = [ "laptop" ];
  };
  fred-laptop = {
    tags = [ "laptop" ];
  };
  backup-server = {
    tags = [ "server" ];
  };
};

inventory.instances = {
  # Networking: direct SSH to each machine
  internet = {
    roles.default.machines."sally-laptop".settings.host  = "192.168.1.10";
    roles.default.machines."fred-laptop".settings.host   = "192.168.1.11";
    roles.default.machines."backup-server".settings.host = "192.168.1.100";
  };

  # SSH on everything
  sshd = {
    roles.server.tags = [ "all" ];
  };

  # WiFi on laptops
  wifi = {
    roles.default.tags = [ "laptop" ];
    roles.default.settings.networks.home = {};
  };

  # One user account per person, on their own machine
  user-sally = {
    module.name = "users";
    roles.default.machines."sally-laptop" = {};
    roles.default.settings.user = "sally";
  };
  user-fred = {
    module.name = "users";
    roles.default.machines."fred-laptop" = {};
    roles.default.settings.user = "fred";
  };

  # Backups: laptops to backup-server, every night at 2 AM
  borgbackup = {
    roles.client.tags = [ "laptop" ];
    roles.client.settings.startAt = "*-*-* 02:00:00";
    roles.server.machines."backup-server" = {};
  };
};
```

Adding `barb-laptop` with `tags = [ "laptop" ]` automatically gives her SSH, WiFi, and a backup slot.
