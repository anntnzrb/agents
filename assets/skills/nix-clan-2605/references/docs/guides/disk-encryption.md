# Disk Encryption

Example ZFS native-encryption setup with remote SSH decryption during boot. Root filesystem becomes encrypted; unlock it remotely over the network.

:::admonition[Secure Boot]{type=info}
Compatible with systems where [secure boot is disabled](secure-boot.md). If boot fails, check whether UEFI secure boot must be disabled.
:::

## Disk Layout Configuration

Find the target disk ID:

```bash
ssh root@nixos-installer.local lsblk --output NAME,ID-LINK,FSTYPE,SIZE,MOUNTPOINT
```

Replace the example disk IDs below with the IDs from this output. Save each configuration as `machines/<mymachine>/disko.nix` and `git add` it so Nix sees it.

::::tabs
:::tab[Single Disk]

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

:::tab[Raid 1]

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

:::
::::

Notes: (1) ESP condition hardcodes the bootable disk. (2) `neededFor = "partitioning"` uploads the generated secret during installation. (3) `zfs-import-zroot` waits until the secret file appears. (4) ZFS reads the passphrase from that file. (5) Replace the example boot-device disk ID(s) with the `lsblk` ID(s).

## Initrd SSH Configuration

Save as `machines/<mymachine>/initrd.nix`, include it in `configuration.nix`, and `git add machines/<mymachine>/initrd.nix`.

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

(1) Replace `<My_SSH_Public_Key>` with your SSH public key. (2) Replace `e1000e` with the target’s network driver; find it with `nix shell nixpkgs#pciutils -c lspci -k`. (3) `neededFor = "activation"` makes the generated host key available in the initrd.

## Installation

Before installation, put your public key on the NixOS installer:

```bash
ssh-copy-id root@nixos-installer.local -i ~/.config/clan/nixos-anywhere/keys/id_ed25519
```

Run:

1. SSH into the installer:
   ```bash
   ssh root@nixos-installer.local
   ```
2. Wipe the target partition table:
   ```bash
   blkdiscard /dev/disk/by-id/<installdisk>
   ```
3. Kexec and partition:
   ```bash
   clan machines install <mymachine> --target-host root@nixos-installer.local --phases kexec,disko
   ```
4. Check logs for errors before continuing.
5. Install NixOS:
   ```bash
   clan machines install <mymachine> --target-host root@nixos-installer.local --phases install
   ```
6. Reboot and remove the USB installer.

## Remote Decryption

After reboot, initrd waits for the encryption key. Test connectivity:

```bash
ssh root@<your-machines-ip> -p 7172
```

Save the following as `machines/<mymachine>/decrypt.sh`, run `chmod +x machines/<mymachine>/decrypt.sh`, and run it on every boot to deliver the key. Replace `HOST` with the machine IP and `MACHINE` with its name.

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
