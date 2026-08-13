# Introduction to Backups

Clan backs up selected machine data to another clan machine or a remote location. It handles BorgBackup encryption, scheduling, deduplication, compression, and restoration.

## Model

Backup inputs: folders, databases, application state. BorgBackup encrypts before transfer; identical data is stored once on the server; compression reduces storage and transfer size.

`borgbackup` roles:

| Role | Function |
|---|---|
| client | Creates and sends backups |
| server | Receives and stores backups |

A machine can have both roles. On each client, declare persistent data with `clan.core.state` in the `machines` attribute of `clan.nix`; configure the backup server separately. `clan.core.state` means “important data,” not “backup”: providers consume it, and backup, restore, migration, or another backup tool can reuse the same definitions. State entries support `preBackupScript` and `postBackupScript`, useful for stopping or flushing databases.

## Starting configuration

Use two machines in one clan, conventionally `alice-laptop` and `backup-server`; record both IP addresses. Replace `meta.name`, `meta.domain`, both target IPs, the backup address, and both indicated SSH public-key placeholders. Install/configure hardware and disks as usual.

```nix
{
  # Ensure this is unique among all clans you want to use.
  meta.name = "MY-BACKUP-CLAN";
  meta.domain = "mybackupclan.lol";

  inventory.machines = {
    alice-laptop = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH ALICE'S IP ADDRESS; keep "root@"
      tags = [ ];
    };
    backup-server = {
      deploy.targetHost = "root@<IP-ADDRESS>"; # REPLACE WITH BACKUP'S IP ADDRESS; keep "root@"
      tags = [ ];
    };

  };

  # Docs: See https://clan.lol/docs/26.05/services/definition
  inventory.instances = {
    borgbackup = {
      roles.client.machines."alice-laptop" = { };
      roles.server.machines."backup-server" = {
        settings.address = "<IP-ADDRESS>"; # REPLACE WITH BACKUP'S IP ADDRESS
        settings.directory = "/var/lib/borgbackup";
      };
    };

    user-alice = {
      module.name = "users";
      roles.default.machines."alice-laptop" = { };
      roles.default.settings = {
        user = "alice";
        openssh.authorizedKeys.keys = [ "PASTE_YOUR_KEY_HERE" ];
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
  # machines/server/configuration.nix will be automatically imported.
  # See: https://clan.lol/docs/26.05/guides/inventory/autoincludes
  machines = {
    alice-laptop =
      { ... }:
      {
        # Create two folders on alice-laptop
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

  };
}
```

Configuration effects:

- `roles.client.machines."alice-laptop"`: client, default settings.
- `roles.server.machines."backup-server"`: server; `settings.address` is the client connection IP and `settings.directory` stores repositories.
- Clan generates client/server SSH keys, configures both services, and schedules client backups.
- `systemd.tmpfiles.rules` creates missing directories on boot. Each rule is `d path mode user group age`; here `d` creates a directory, `0755` sets permissions, `alice`/`users` set ownership, and `-` disables automatic cleanup.
- State label `my-documents` is arbitrary; `folders` lists tracked paths. Providers automatically include these folders.

## Install

Run `clan machines install`, installing `backup-server` first: the client needs the server’s SSH host key.

## Exercise

Log in to `alice-laptop` as `alice`. To retrieve her password from the setup machine:

```text
clan vars get alice-laptop user-password-alice/user-password
```

```bash
ssh alice@<IP-ADDRESS>
```

On the laptop, create sample state:

```bash
cd documents
nano welcome.md
```

```text
Hello World!
```

Save with Ctrl+O, Enter; exit with Ctrl+X. Create another file:

```bash
nano finance.txt
```

```text
Account total: 5000
```

Save and exit as above. Add an image:

```bash
cd ~
cd pictures
```

```text
curl -o hero.jpg https://clan.lol/_assets/25.11/_app/immutable/assets/docs-hero.CUEOsCNu.jpg
```

NixOS includes `curl` by default, not `wget`. Verify, then leave the laptop:

```text
cd ~
ls documents
ls pictures

```

Expected: two files in `documents`, `hero.jpg` in `pictures`.

```bash
exit
```

## Create and restore

From the setup machine, start an immediate backup across all configured providers:

```bash
clan backups create alice-laptop
```

Expected:

```text
successfully started backup
```

Wait about a minute, then list backups:

```bash
clan backups list alice-laptop
```

Example output:

```text
backup-server::borg@<IP-ADDRESS>:.::alice-laptop-backup-server-2026-04-14T03:53:34
```

Delete a file on the laptop:

```text
cd documents
rm welcome.md
```

```bash
exit
```

List again on the setup machine. Multiple entries are possible after multiple backups; choose the most recent backup name:

```bash
clan backups list alice-laptop
```

```text
backup-server::borg@<IP-ADDRESS>:.::alice-laptop-backup-server-2026-04-14T03:53:34
```

Restore with provider `borgbackup` and the selected name:

```bash
clan backups restore alice-laptop borgbackup <PASTE>
```

Example:

```bash
clan backups restore alice-laptop borgbackup backup-server::borg@<IP-ADDRESS>:.::alice-laptop-backup-server-2026-04-14T03:53:34
```

Log back in, run `ls` in `documents`, and verify `welcome.md` is restored.

## Command reference

`clan backups create <machine>` — immediate backup across all configured providers.

`clan backups list <machine>` — list existing backups; optional `--provider` filters by provider.

`clan backups restore <machine> <provider> <name>` — restore a named backup. `<provider>` is the configured destination name; `<name>` comes from `clan backups list`.
