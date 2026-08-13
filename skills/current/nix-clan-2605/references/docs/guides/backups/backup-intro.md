# Backup Intro

Clan machines: automated, encrypted, secure, deduplicated backups via [BorgBackup](https://www.borgbackup.org/), enabling file/database restoration.

## File and Directory Backups

Configure each state in the machine's NixOS configuration; `folders` accepts multiple absolute directory paths and backs up all contained files/subdirectories.

### Application-data example

```nix
{
  clan.core.state.nextcloud = {
    folders = [
      "/var/lib/nextcloud" # Main application data
      "/etc/nextcloud" # Configuration files
    ];
  };
}
```

## Hooks

Lifecycle hooks run custom preparation, service control, synchronization, or cleanup scripts:

|Hook|When It Executes|Common Use Cases|
|---|---|---|
|`preBackupScript`|Before backup starts|Stop services, dump databases, sync files|
|`postBackupScript`|After backup completes|Restart services, cleanup temp files|
|`preRestoreScript`|Before restoration starts|Prepare system, stop conflicting services|
|`postRestoreScript`|After restoration completes|Restart services, verify integrity|

### Pre/post backup example

The `nextcloud` example stops relevant services before data synchronization and starts them afterward.

```nix
clan.core.state.nextcloud = {
  folders = [ "/var/lib/nextcloud" ];
  preBackupScript = ''
    export PATH=${
      lib.makeBinPath [
        config.systemd.package
      ]
    }

      systemctl stop phpfpm-nextcloud.service
      systemctl stop nextcloud-cron.timer
  '';

  postBackupScript = ''
    export PATH=${
      lib.makeBinPath [
        config.systemd.package
      ]
    }

    systemctl start phpfpm-nextcloud.service
    systemctl start nextcloud-cron.timer
  '';
};
```

:::admonition[Example: Pre and Post Restore Scripts]{type=tip collapsible}

```nix
clan.core.state.linkding = {
  folders = [ "/var/backup/linkding" ];

  # Script to run before creating a backup
  preBackupScript = ''
    export PATH=${
      lib.makeBinPath [
        config.systemd.package
        pkgs.coreutils
        pkgs.rsync
      ]
    }

    # Check if the service is running
    service_status=$(systemctl is-active podman-linkding)

    if [ "$service_status" = "active" ]; then
      # Stop the service and sync data to the backup directory
      systemctl stop podman-linkding
      rsync -avH --delete --numeric-ids "/data/podman/linkding/" /var/backup/linkding/
      systemctl start podman-linkding
    fi
  '';

  # Script to run after restoring a backup
  postRestoreScript = ''
    export PATH=${
      lib.makeBinPath [
        config.systemd.package
        pkgs.coreutils
        pkgs.rsync
      ]
    }

    # Check if the service is running
    service_status="$(systemctl is-active podman-linkding)"

    if [ "$service_status" = "active" ]; then
      # Stop the service
      systemctl stop podman-linkding

      # Backup current data locally
      cp -rp "/data/podman/linkding" "/data/podman/linkding.bak"

      # Restore data from the backup directory
      rsync -avH --delete --numeric-ids /var/backup/linkding/ "/data/podman/linkding/"

      # Restart the service
      systemctl start podman-linkding
    fi
  '';
};
```

:::

---

## Database Backups

Clan provides integrated PostgreSQL backups:

```nix
{
  # Enable the PostgreSQL backup module
  clan.core.postgresql.enable = true;

  # Configure each database
  clan.core.postgresql.databases.nextcloud = {
    # Database creation options (runs on first setup)
    create = {
      TEMPLATE = "template0";
      LC_COLLATE = "C";
      LC_CTYPE = "C";
      ENCODING = "UTF8";
      OWNER = "nextcloud";
    };

    # Services to stop during restore (for consistency)
    restore.stopOnRestore = [
      "phpfpm-nextcloud.service"
      "nextcloud-cron.timer"
    ];
  };
}
```

PostgreSQL integration:
- Automatically dumps each database before every backup.
- Stores dumps securely in the backup repository.
- Manages restore service dependencies.
- Recreates databases with correct settings on new deployments.
