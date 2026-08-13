# More on Backups

## Backup hooks

Hooks belong to `clan.core.state`, not the backup service: they protect live, mutable data from inconsistent snapshots. Use them for containers, databases, VMs, mail delivery, append-only monitoring data (Prometheus/InfluxDB), and log rotation.

```nix
  machines = {

    docker-host = { config, ... }: {
      clan.core.state."containers" = {
        folders = [ "/var/lib/docker/volumes" ];
        preBackupScript = ''
          docker pause $(docker ps -q)
        '';
        postBackupScript = ''
          docker unpause $(docker ps -q)
        '';
      };
    };

  };

```

Hooks:

|Hook|When It Runs|
|---|---|
|`preBackupScript`|Before the backup starts|
|`postBackupScript`|After the backup finishes|
|`preRestoreScript`|Before a restore starts|
|`postRestoreScript`|After a restore finishes|

## PostgreSQL backups

`clan.core.postgresql` integrates PostgreSQL backup/restore with Clan; use it instead of manually writing dump/restore hooks.

```nix
{
  # Ensure this is unique among all clans you want to use.
  meta.name = "MY-HETZNER-CLAN";
  meta.domain = "myhetznerclan.lol";

  inventory.machines = {
    postgres-server = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH POSTGRES-SERVER'S IP ADDRESS; keep "root@"
      tags = [ ];
    };
    backup-server = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH BACKUP-SERVER'S IP ADDRESS; keep "root@"
      tags = [ ];
    };
  };

  # Docs: See https://clan.lol/docs/26.05/services/definition
  inventory.instances = {

    borgbackup = {
      roles.client.machines."postgres-server" = { };
      roles.server.machines."backup-server" = {
        settings.address = "<IP-ADDRESS>"; # REPLACE WITH BACKUP-SERVER'S IP ADDRESS
        settings.directory = "/var/lib/borgbackup";
      };
    };

    # Docs: https://clan.lol/docs/26.05/services/official/sshd
    # SSH service for secure remote access to machines.
    # Generates persistent host keys and configures authorized keys.
    sshd = {
      roles.server.tags.all = { };
      roles.server.settings.authorizedKeys = {
        # Insert the public key that you want to use for SSH access.
        # All keys will have ssh access to all machines ("tags.all" means 'all machines').
        # Alternatively set 'users.users.root.openssh.authorizedKeys.keys' in each machine
        "admin-machine-1" = "[PASTE_YOUR_KEY_HERE]";
      };
    };

    # Docs: https://clan.lol/docs/26.05/services/official/users
    # Root password management for all machines.
    user-root = {
      module = {
        name = "users";
      };
      roles.default.tags.all = { };
      roles.default.settings = {
        user = "root";
        prompt = true;
      };
    };

  };

  # Additional NixOS configuration can be added here.
  # machines/server/configuration.nix will be automatically imported.
  # See: https://clan.lol/docs/26.05/guides/inventory/autoincludes
  machines = {

    postgres-server =
      { config, ... }:
      {
        services.postgresql = {
          enable = true;
          ensureDatabases = [ "mydatabase" ];
        };

        clan.core.postgresql.enable = true;
        clan.core.postgresql.databases.mydatabase = { };

        clan.core.state."postgresql" = {
          folders = [ ];
          preBackupScript = ''
            systemctl stop postgresql
          '';
          postBackupScript = ''
            systemctl start postgresql
          '';
        };
      };

  };
}
```

## Two machines → one backup server

A borgbackup client can be selected by tag (`roles.client.tags`), so tagging another machine includes it; explicit `roles.client.machines` also selects clients.

### Installation order

Install/generate vars for the machine providing a cross-machine secret before its consumers. Borgbackup clients need the server SSH host key, generated during server installation; installing a client first requires regenerating its vars.

```bash
clan machines install backup-server --target-host root@<BACKUP-IP>
```

```bash
clan machines install postgres-server --target-host root@<POSTGRES-IP>
```

```bash
clan machines install alice-laptop --target-host root@<ALICE-IP>
```

```nix
{
  # Ensure this is unique among all clans you want to use.
  meta.name = "MY-BACKUP-CLAN";
  meta.domain = "mybackupclan.lol";

  inventory.machines = {
    alice-laptop = {
      deploy.targetHost = "root@192.168.56.101";
      tags = [ "employees" ];
    };
    backup-server = {
      deploy.targetHost = "root@192.168.56.104";
      tags = [ ];
    };
    postgres-server = {
      deploy.targetHost = "root@192.168.56.102";
      tags = [ ];
    };
  };

  inventory.instances = {
    borgbackup = {
      roles.client.tags = [ "employees" ];
      roles.client.machines."postgres-server" = { };
      roles.server.machines."backup-server" = {
        settings.address = "192.168.56.104";
        settings.directory = "/var/lib/borgbackup";
      };
    };

    user-alice = {
      module.name = "users";
      roles.default.machines."alice-laptop" = { };
      roles.default.settings = {
        user = "alice";
        openssh.authorizedKeys.keys = [
          "PASTE_YOUR_KEY_HERE"
        ];
      };
    };

    sshd = {
      roles.server.tags.all = { };
      roles.server.settings.authorizedKeys = {
        "admin-machine-1" =
          "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAZGMNlooljzJfmzQKaVcmj4tRYW+gqBIfdWbG0NU3XL freckleface@freckleface--Laptop";
      };
    };

    user-root = {
      module.name = "users";
      roles.default.tags.all = { };
      roles.default.settings = {
        user = "root";
        prompt = true;
      };
    };
  };

  machines = {

    alice-laptop =
      { ... }:
      {
        systemd.tmpfiles.rules = [
          "d /home/alice/documents 0755 alice users -"
          "d /home/alice/pictures 0755 alice users -"
        ];

        clan.core.state."my-documents" = {
          folders = [
            "/home/alice/documents"
            "/home/alice/pictures"
          ];
        };
      };

    postgres-server =
      { config, ... }:
      {
        services.postgresql = {
          enable = true;
          ensureDatabases = [ "mydb" ];
        };

        clan.core.postgresql.enable = true;
        clan.core.postgresql.databases.mydb = { };

        clan.core.state."postgresql" = {
          folders = [ ];
          preBackupScript = ''
            systemctl stop postgresql
          '';
          postBackupScript = ''
            systemctl start postgresql
          '';
        };
      };

  };
}
```

## Exclusions

```nix
roles.client.tags.employees.settings = {
  exclude = [ "*.bak" ];
}
```

This excludes `*.bak` on every machine tagged `employees`.

```nix
inventory.instances = {
  borgbackup = {
    roles.client.machines."alice-laptop" = {
      settings.exclude = [
        "*.pyc"
        "*.tmp"
        "__pycache__"
        ".cache"
      ];
    };
    roles.server.machines."backup-server" = {};
  };
};
```

## Backup schedule

Default: daily at 1:00 AM. Set `settings.startAt` per client; values use [systemd calendar event syntax](https://www.freedesktop.org/software/systemd/man/systemd.time.html).

```nix
inventory.instances = {
  borgbackup = {
    roles.client.machines."alice-laptop" = {
      settings.startAt = "*-*-* 04:00:00";   # 4 AM daily
    };
    roles.server.machines."backup-server" = {};
  };
};
```

|Schedule|Meaning|
|---|---|
|`*-*-* 01:00:00`|Every day at 1 AM (default)|
|`*-*-* 04:00:00`|Every day at 4 AM|
|`*-*-* *:00:00`|Every hour|
|`Mon *-*-* 03:00:00`|Every Monday at 3 AM|

```nix
# clan.nix
{
  inventory.machines = {
    laptop = {
      deploy.targetHost = "root@192.168.1.10";
      tags = [ "workstation" ];
    };
    desktop = {
      deploy.targetHost = "root@192.168.1.11";
      tags = [ "workstation" ];
    };
    work-pc = {
      deploy.targetHost = "root@192.168.1.12";
      tags = [ "workstation" ];
    };
    nas = {
      deploy.targetHost = "root@192.168.1.50";
    };
  };

  inventory.instances = {
    borgbackup = {
      roles.client.machines = {
        "laptop" = {
          settings.startAt = "*-*-* 02:00:00";
        }; # 2 AM
        "desktop" = {
          settings.startAt = "*-*-* 03:00:00";
        }; # 3 AM
        "work-pc" = {
          settings.startAt = "*-*-* 04:00:00";
        }; # 4 AM
      };
      roles.server.machines."nas" = {
        settings.address = "192.168.1.50";
        settings.directory = "/data/backups";
      };
    };
  };
}
```

## External destinations

Backups may target an external Hetzner Storage Box or any SSH-accessible BorgBackup server. For Hetzner, enable **Allow SSH** and **External Reachability** under **Additional Settings**, and add your `id_ed25519.pub` key. Create a Clan, replace `clan.nix` with the following, fill in the clan name/domain and storage-box values, create `postgres-server`, gather hardware configuration, and configure a disk as usual.

```nix
{
  # Ensure this is unique among all clans you want to use.
  meta.name = "MY-HETZNER-CLAN";
  meta.domain = "myhetznerclan.lol";

  inventory.machines = {
    postgres-server = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH postgres-server's IP ADDRESS; keep "root@"
      tags = [ ];
    };
  };

  inventory.instances = {

    borgbackup = {
      roles.client.machines."postgres-server" = {
        settings.destinations."storagebox" = {
          repo = "<BOX-USERID>@<BOX-USERID>.your-storagebox.de:/./borgbackup"; # REPLACE WITH USERNAME FROM STORAGE BOX DETAILS PAGE
          rsh = "ssh -p 23 -oStrictHostKeyChecking=accept-new -i /run/secrets/vars/borgbackup/borgbackup.ssh";
        };
      };
    };

    sshd = {
      roles.server.tags.all = { };
      roles.server.settings.authorizedKeys = {
        # Insert the public key that you want to use for SSH access.
        # All keys will have ssh access to all machines ("tags.all" means 'all machines').
        # Alternatively set 'users.users.root.openssh.authorizedKeys.keys' in each machine
        "admin-machine-1" = "PASTE_YOUR_KEY_HERE";
      };
    };

    user-root = {
      module = {
        name = "users";
      };
      roles.default.tags.all = { };
      roles.default.settings = {
        user = "root";
        prompt = true;
      };
    };

  };

  machines = {

    postgres-server =
      { config, ... }:
      {
        services.postgresql = {
          enable = true;
          ensureDatabases = [ "mydatabase" ];
        };

        clan.core.postgresql.enable = true;
        clan.core.postgresql.databases.mydatabase = { };

        clan.core.state."postgresql" = {
          folders = [ ];
          preBackupScript = ''
            systemctl stop postgresql
          '';
          postBackupScript = ''
            systemctl start postgresql
          '';
        };
      };

  };
}
```

Copy the Storage Box username and server URL from its web-console overview into `clan.nix`. Install `postgres-server`; Clan generates the borgbackup SSH keypair. Retrieve its public key and upload it to the destination. For a non-Hetzner SSH-accessible server, use the printed key from the first command; for Hetzner, use the second command, which pipes it directly:

```bash
# For non-Hetzner: Get the public key Clan generated
clan vars get postgres-server borgbackup/borgbackup.ssh.pub

# For Hetzner Storage Box, you can pipe it directly:
clan vars get postgres-server borgbackup/borgbackup.ssh.pub | ssh -p23 <BOX-USERID>@<BOX-USERID>.your-storagebox.de install-ssh-key
```

`rsh` is Borg's remote-shell command: SSH port 23 for Hetzner; `accept-new` accepts a new host key but rejects later changes; `-i /run/secrets/vars/borgbackup/borgbackup.ssh` selects Clan's generated private key, deployed on `postgres-server` in RAM-only `/run/secrets/` and paired with the uploaded public key. `yes` would require a preexisting `known_hosts` entry; `no` would accept blindly and is insecure.

```nix
rsh = "ssh -p 23 -oStrictHostKeyChecking=accept-new -i /run/secrets/vars/borgbackup/borgbackup.ssh";
```

## Multiple destinations per client

A client backs up to every `borgbackup` server for which it is a client plus every explicit `settings.destinations` entry. Clan generates one systemd `borgbackup-job-*` unit per destination; jobs share the schedule and independently run the pre/post hooks.

```nix
{
  # Ensure this is unique among all clans you want to use.
  meta.name = "MY-BACKUP-CLAN";
  meta.domain = "mybackupclan.lol";

  inventory.machines = {
    postgres-server = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH POSTGRES-SERVER'S IP ADDRESS; keep "root@"
      tags = [ ];
    };
    backup-server = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH BACKUP-SERVER'S IP ADDRESS; keep "root@"
      tags = [ ];
    };
  };

  # Docs: See https://clan.lol/docs/26.05/services/definition
  inventory.instances = {

    borgbackup = {
      roles.client.machines."postgres-server" = {
        # declares postgres-server a client (ONE time)
        settings.destinations."storagebox" = {
          # Destination #1
          repo = "<HETZNER-USER>@<HETZNER-USER>.your-storagebox.de:/./borgbackup"; # REPLACE <HETZNER-USER> with your Hetzner storage box username
          rsh = "ssh -p 23 -oStrictHostKeyChecking=accept-new -i /run/secrets/vars/borgbackup/borgbackup.ssh";
        };
      };
      roles.server.machines."backup-server" = {
        # default server
        settings.address = "<IP-ADDRESS>"; # REPLACE WITH BACKUP-SERVER'S IP ADDRESS
        settings.directory = "/var/lib/borgbackup";
      };
    };

    # Docs: https://clan.lol/docs/26.05/services/official/sshd
    # SSH service for secure remote access to machines.
    sshd = {
      roles.server.tags.all = { };
      roles.server.settings.authorizedKeys = {
        "admin-machine-1" = "PASTE_YOUR_KEY_HERE";
      };
    };

    # Docs: https://clan.lol/docs/26.05/services/official/users
    # Root password management for all machines.
    user-root = {
      module = {
        name = "users";
      };
      roles.default.tags.all = { };
      roles.default.settings = {
        user = "root";
        prompt = true;
      };
    };
  };

  # Additional NixOS configuration can be added here.
  machines = {

    postgres-server =
      { config, ... }:
      {
        services.postgresql = {
          enable = true;
          ensureDatabases = [ "mydatabase" ];
        };

        clan.core.postgresql.enable = true;
        clan.core.postgresql.databases.mydatabase = { };

        clan.core.state."postgresql" = {
          folders = [ ];
          preBackupScript = ''
            systemctl stop postgresql
          '';
          postBackupScript = ''
            systemctl start postgresql
          '';
        };
      };

  };
}
```

This configuration creates `borgbackup-job-backup-server` (local VM) and `borgbackup-job-storagebox` (Hetzner) for `postgres-server`; PostgreSQL is stopped/started around each job independently.
