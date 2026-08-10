# Disk Encryption

This guide provides an example setup for a ZFS system with native encryption and remote decryption over SSH.

This guide walks you through setting up a ZFS system with native encryption and remote decryption via SSH. After completing this guide, your machine's root filesystem will be encrypted, and you will be able to unlock it remotely over the network during boot.

:::admonition[Secure Boot]{type=info}
This guide is compatible with systems that have [secure boot disabled](secure-boot.md). If you encounter boot issues, check if secure boot needs to be disabled in your UEFI settings.
:::

## Contents

- [Disk Layout Configuration](#disk-layout-configuration)
- [Initrd SSH Configuration](#initrd-ssh-configuration)
- [Installation](#installation)
  - [Copy SSH Public Key](#copy-ssh-public-key)
  - [Prepare Disks and Install](#prepare-disks-and-install)
- [Remote Decryption](#remote-decryption)


## Disk Layout Configuration

Replace the highlighted lines below with your own disk ID.
You can find out your disk ID by running:

```bash
ssh root@nixos-installer.local lsblk --output NAME,ID-LINK,FSTYPE,SIZE,MOUNTPOINT
```

::::tabs
:::tab[Single Disk]

- Copy the configuration below into `machines/<mymachine>/disko.nix`.
- Don't forget to `git add machines/<mymachine>/disko.nix` so that Nix sees the file.

```nix [disko.nix]
{
  config,
  lib,
  pkgs,
  ...
}:
let
  mirrorBoot = idx: {
    # suffix is to prevent disk name collisions
    name = idx;
    type = "disk";
    device = "/dev/disk/by-id/${idx}";
    content = {
      type = "gpt";
      partitions = {
        "boot" = {
          size = "1M";
          type = "EF02"; # for grub MBR
          priority = 1;
        };
        "ESP" = lib.mkIf (idx == "ata-HGST_HUS726020ALE610_K5HEJXVD") {
          # (1)
          size = "1G";
          type = "EF00";
          content = {
            type = "filesystem";
            format = "vfat";
            mountpoint = "/boot";
            mountOptions = [ "nofail" ];
          };
        };
        "root" = {
          size = "100%";
          content = {
            type = "zfs";
            pool = "zroot";
          };
        };
      };
    };
  };
in
{
  imports = [ ];

  config = {

    # generates the encryption key
    clan.core.vars.generators.zfs = {
      files.key.neededFor = "partitioning"; # (2)
      runtimeInputs = [
        pkgs.xkcdpass
      ];
      script = ''
        xkcdpass -d - -n 8 | tr -d '\n' > $out/key
      '';
    };

    # service that waits for the zfs key
    boot.initrd.systemd.services.zfs-import-zroot = {
      # (3)
      preStart = ''
        while [ ! -f ${config.clan.core.vars.generators.zfs.files.key.path} ]; do 
          sleep 1
        done
      '';
      unitConfig = {
        StartLimitIntervalSec = 0;
      };
      serviceConfig = {
        RestartSec = "1s";
        Restart = "on-failure";
      };
    };

    boot.loader.grub = {
      enable = true;
      efiSupport = true;
      efiInstallAsRemovable = true;
      devices = [
        "/dev/disk/by-id/ata-HGST_HUS726020ALE610_K5HEJXVD" # (5)
      ];
    };

    disko.devices = {
      disk = {
        x = mirrorBoot "ata-HGST_HUS726020ALE610_K5HEJXVD";
      };
      zpool = {
        zroot = {
          type = "zpool";
          rootFsOptions = {
            compression = "lz4";
            acltype = "posixacl";
            xattr = "sa";
            "com.sun:auto-snapshot" = "true";
            mountpoint = "none";
          };
          datasets = {
            "root" = {
              type = "zfs_fs";
              options = {
                mountpoint = "none";
                encryption = "aes-256-gcm";
                keyformat = "passphrase";
                keylocation = "file://${config.clan.core.vars.generators.zfs.files.key.path}"; # (4)
              };
            };
            "root/nixos" = {
              type = "zfs_fs";
              options.mountpoint = "/";
              mountpoint = "/";
            };
            "root/home" = {
              type = "zfs_fs";
              options.mountpoint = "/home";
              mountpoint = "/home";
            };
            "root/tmp" = {
              type = "zfs_fs";
              mountpoint = "/tmp";
              options = {
                mountpoint = "/tmp";
                sync = "disabled";
              };
            };
          };
        };
      };
    };
  };
}
```

1. Hardcodes this disk as a bootable disk
2. Marks the generated secret as needed during the partitioning phase, so it will be uploaded during installation
3. Stalls the boot process until the decryption secret file appears at the expected location
4. Tells ZFS to read the decryption passphrase from a file
5. Replace with the disk ID from the `lsblk` output above

:::
:::tab[Raid 1]

- Copy the configuration below into `machines/<mymachine>/disko.nix`.
- Don't forget to `git add machines/<mymachine>/disko.nix` so that Nix sees the file.

```nix [disko.nix]
{
  config,
  lib,
  pkgs,
  ...
}:
let
  mirrorBoot = idx: {
    # suffix is to prevent disk name collisions
    name = idx;
    type = "disk";
    device = "/dev/disk/by-id/${idx}";
    content = {
      type = "gpt";
      partitions = {
        "boot" = {
          size = "1M";
          type = "EF02"; # for grub MBR
          priority = 1;
        };
        "ESP" = lib.mkIf (idx == "ata-HGST_HUS726020ALE610_K5HEJXVD") {
          # (1)
          size = "1G";
          type = "EF00";
          content = {
            type = "filesystem";
            format = "vfat";
            mountpoint = "/boot";
            mountOptions = [ "nofail" ];
          };
        };
        "root" = {
          size = "100%";
          content = {
            type = "zfs";
            pool = "zroot";
          };
        };
      };
    };
  };
in
{
  imports = [ ];

  config = {

    # generates the encryption key
    clan.core.vars.generators.zfs = {
      files.key.neededFor = "partitioning"; # (2)
      runtimeInputs = [
        pkgs.xkcdpass
      ];
      script = ''
        xkcdpass -d - -n 8 | tr -d '\n' > $out/key
      '';
    };

    # service that waits for the zfs key
    boot.initrd.systemd.services.zfs-import-zroot = {
      # (3)
      preStart = ''
        while [ ! -f ${config.clan.core.vars.generators.zfs.files.key.path} ]; do
          sleep 1
        done
      '';
      unitConfig = {
        StartLimitIntervalSec = 0;
      };
      serviceConfig = {
        RestartSec = "1s";
        Restart = "on-failure";
      };
    };

    boot.loader.grub = {
      enable = true;
      efiSupport = true;
      efiInstallAsRemovable = true;
      devices = [
        "/dev/disk/by-id/ata-HGST_HUS726020ALE610_K5HEJXVD" # (5)
        "/dev/disk/by-id/ata-HGST_HUS722T2TALA600_WMC6N0L89MU9"
      ];
    };

    disko.devices = {
      disk = {
        x = mirrorBoot "ata-HGST_HUS726020ALE610_K5HEJXVD";
        y = mirrorBoot "ata-HGST_HUS722T2TALA600_WMC6N0L89MU9";
      };
      zpool = {
        zroot = {
          type = "zpool";
          rootFsOptions = {
            compression = "lz4";
            acltype = "posixacl";
            xattr = "sa";
            "com.sun:auto-snapshot" = "true";
            mountpoint = "none";
          };
          datasets = {
            "root" = {
              type = "zfs_fs";
              options = {
                mountpoint = "none";
                encryption = "aes-256-gcm";
                keyformat = "passphrase";
                keylocation = "file://${config.clan.core.vars.generators.zfs.files.key.path}"; # (4)
              };
            };
            "root/nixos" = {
              type = "zfs_fs";
              options.mountpoint = "/";
              mountpoint = "/";
            };
            "root/home" = {
              type = "zfs_fs";
              options.mountpoint = "/home";
              mountpoint = "/home";
            };
            "root/tmp" = {
              type = "zfs_fs";
              mountpoint = "/tmp";
              options = {
                mountpoint = "/tmp";
                sync = "disabled";
              };
            };
          };
        };
      };
    };
  };
}
```

1. Hardcodes this disk as a bootable disk
2. Marks the generated secret as needed during the partitioning phase, so it will be uploaded during installation
3. Stalls the boot process until the decryption secret file appears at the expected location
4. Tells ZFS to read the decryption passphrase from a file
5. Replace with the disk IDs from the `lsblk` output above
:::
::::

## Initrd SSH Configuration

Next, copy the configuration below into `machines/<mymachine>/initrd.nix` and include it in your `configuration.nix`.
Don't forget to `git add machines/<mymachine>/initrd.nix` so that Nix sees the file.

```nix [initrd.nix]
{ config, pkgs, ... }:

{

  boot.initrd.systemd = {
    enable = true;
  };

  # generates host keys for the initrd ssh daemon
  clan.core.vars.generators.initrd-ssh = {
    files."id_ed25519".neededFor = "activation"; # (3)
    files."id_ed25519.pub".secret = false;
    runtimeInputs = [
      pkgs.coreutils
      pkgs.openssh
    ];
    script = ''
      ssh-keygen -t ed25519 -N "" -f $out/id_ed25519
    '';
  };

  boot.initrd.network = {
    enable = true;

    ssh = {
      enable = true;
      port = 7172;
      authorizedKeys = [
        "<My_SSH_Public_Key>" # (1)
      ];
      hostKeys = [
        config.clan.core.vars.generators.initrd-ssh.files.id_ed25519.path
      ];
    };
  };

  boot.initrd.availableKernelModules = [
    "xhci_pci"
  ];

  # Find out the required network card driver by running `nix shell nixpkgs#pciutils -c lspci -k` on the target machine
  boot.initrd.kernelModules = [ "e1000e" ]; # (2)
}
```

1. Replace `<My_SSH_Public_Key>` with your SSH public key.
2. Replace with the network driver used by the target device. You can find the correct module by running `nix shell nixpkgs#pciutils -c lspci -k` on the target.
3. Marks the generated secret as needed during the activation phase, so it will be available in the initrd.

## Installation

### Copy SSH Public Key

Before starting the installation, ensure that your SSH public key is on the NixOS installer.

Copy your public SSH key to the installer if you have not done so already:

```bash
ssh-copy-id root@nixos-installer.local -i ~/.config/clan/nixos-anywhere/keys/id_ed25519
```

### Prepare Disks and Install

1. SSH into the installer:

    ```bash
    ssh root@nixos-installer.local
    ```

2. Wipe the existing partition table from the target disk:

    ```bash
    blkdiscard /dev/disk/by-id/<installdisk>
    ```

3. Run kexec and partition the disks:

    ```bash
    clan machines install <mymachine> --target-host root@nixos-installer.local --phases kexec,disko
    ```

4. Check the logs for errors before proceeding.

5. Install NixOS onto the partitioned disks:

    ```bash
    clan machines install <mymachine> --target-host root@nixos-installer.local --phases install
    ```

6. Reboot the machine and remove the USB installer.

## Remote Decryption

After rebooting, the machine will pause in the initrd and wait for the encryption key before continuing to boot. You can verify connectivity by SSHing into the initrd environment:

```bash
ssh root@<your-machines-ip> -p 7172
```

To automate the decryption step, create the following script:

- Save it as `machines/<mymachine>/decrypt.sh`.
- Make it executable with `chmod +x machines/<mymachine>/decrypt.sh`.
- Run it whenever the machine boots to deliver the encryption key.

```bash [decrypt.sh] {4,5}
#!/usr/bin/env bash
set -euxo pipefail

HOST="192.0.2.1" # (1)
MACHINE="<mymachine>" # (2)
while ! ping -W 1 -c 1 "$HOST"; do
  sleep 1
done
while ! timeout --foreground 10 ssh -p 7172 "root@$HOST" true; do
  sleep 1
done

# Ensure that /run/partitioning-secrets/zfs/key only ever exists with the full key
clan vars get "$MACHINE" zfs/key | ssh -p 7172 "root@${HOST}" "mkdir -p /run/partitioning-secrets/zfs && cat > /run/partitioning-secrets/zfs/key.tmp && mv /run/partitioning-secrets/zfs/key.tmp /run/partitioning-secrets/zfs/key"
```

1. Replace with your machine's IP address
2. Replace with your machine's name
