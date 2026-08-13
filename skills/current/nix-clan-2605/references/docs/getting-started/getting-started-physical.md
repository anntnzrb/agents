# Getting Started: Physical Machine Target

:::admonition[Tip]{type=tip}
Virtual-machine target: [Find the guide here](getting-started-virtualbox.md).
:::

:::admonition[Prerequisites]{type=note}
Setup machine requirements:

* **Nix** (unless NixOS): [Install Nix and direnv](install-nix.md).
* **SSH key**: [Create an SSH key](create-an-ssh-key.md).
* **Git** (Optional): [installation instructions](https://git-scm.com/install/linux). Clan uses Git internally.
:::

<!-- nix-clan-updater:toc:start -->
## Table of Contents
- [Terminology](#terminology)
- [1. Create the clan](#1-create-the-clan)
- [2. Create a machine configuration](#2-create-a-machine-configuration)
- [3. Add your allowed keys](#3-add-your-allowed-keys)
- [4. Enable WiFi on Target Machine (Optional)](#4-enable-wifi-on-target-machine-optional)
- [5. Create an Installer USB Drive](#5-create-an-installer-usb-drive)
- [6. Plug in and Run the Installer](#6-plug-in-and-run-the-installer)
- [7. Enabling Wireless *During* Installation](#7-enabling-wireless-during-installation)
- [8. Configure SSH access](#8-configure-ssh-access)
- [9. Get Hardware Configuration](#9-get-hardware-configuration)
- [10. Add a disk configuration](#10-add-a-disk-configuration)
- [11. Install](#11-install)
  - [If you get an error about Sandboxing](#if-you-get-an-error-about-sandboxing)
- [12. Configure Access and Connect](#12-configure-access-and-connect)
- [Practice: Configuring Users](#practice-configuring-users)
  - [Add a New User (no sudo access)](#add-a-new-user-no-sudo-access)
  - [Give that user sudo access](#give-that-user-sudo-access)
  - [Revoke the sudo access](#revoke-the-sudo-access)
<!-- nix-clan-updater:toc:end -->

## Terminology

- **Setup machine**: computer used to manage other machines.
- **Target machine**: physical or virtual machine being managed.
- **Machine configuration**: Clan's internal target-machine representation.

## 1. Create the clan

```console
nix run https://clan.lol/install/26.05 --refresh -- init
```

Enter a clan name, e.g. `MY-CLAN-1`, then a domain, e.g. `myclan1.lol` (it need not be registered). First run creates an age key at `~/.config/sops/age/keys.txt` for secret encryption: back it up safely, then type "y". If previously run, select admin keys; usually type "1" and press Enter.

```bash
cd MY-CLAN-1
```

Approve direnv:

```bash
direnv allow
```

## 2. Create a machine configuration

```bash
clan machines create test-machine
```

In `clan.nix`, add immediately after `inventory.machines`:

```nix [clan.nix] {2,3,4,5}
inventory.machines = { # FIND THIS LINE, ADD THE FOLLOWING
    test-machine = {
        tags = [ "test" ];
    };
```

```bash
clan machines list
```

## 3. Add your allowed keys

Get the setup machine's public key, replace `PASTE_YOUR_KEY_HERE` in `clan.nix`, then validate:

```bash
cat ~/.ssh/id_ed25519.pub
```

```nix
"admin-machine-1" = "PASTE_YOUR_KEY_HERE";
```

```bash
clan show
```

## 4. Enable WiFi on Target Machine (Optional)

For post-installation WiFi management, add under `inventory.instances`:

```nix [clan.nix] {2-6}
  inventory.instances = {
    wifi = {
      roles.default.machines."test-machine" = {
        settings.networks.home = { };
      };
    };
```

## 5. Create an Installer USB Drive

Use a USB drive with at least 1.5 GB total space.

:::admonition[Danger]{type=note}
All data on the USB drive will be lost!
:::

Download the ISO matching the target architecture:

x86_64:

```bash
wget https://github.com/nix-community/nixos-images/releases/download/nixos-26.05/nixos-installer-x86_64-linux.iso
```

aarch64 (ARM):

```bash
wget https://github.com/nix-community/nixos-images/releases/download/nixos-26.05/nixos-installer-aarch64-linux.iso
```

Insert the USB into the setup machine. Identify its block device with `lsblk`, matching the `SIZE` column (likely `sda` or `sdb`):

```bash
lsblk
```

```console {2}
NAME                                          MAJ:MIN RM   SIZE RO TYPE  MOUNTPOINTS
sdb                                             8:0    1 117,2G  0 disk
└─sdb1                                          8:1    1 117,2G  0 part  /run/media/qubasa/INTENSO
nvme0n1                                       259:0    0   1,8T  0 disk
├─nvme0n1p1                                   259:1    0   512M  0 part  /boot
└─nvme0n1p2                                   259:2    0   1,8T  0 part
    └─luks-f7600028-9d83-4967-84bc-dd2f498bc486 254:0    0   1,8T  0 crypt /nix/store
```

Unmount every mounted partition; replace `sdb` with your device and repeat as needed:

```bash
sudo umount /dev/sdb1
sudo umount /dev/sdb2
sudo umount /dev/sdb3
```

Flash the ISO; replace `<ISO_FILE>` and `<USB_DEVICE>` (device name without `/dev/`, e.g. `sdb`):

```bash
sudo dd if=<ISO_FILE> of=/dev/<USB_DEVICE> bs=4M status=progress conv=fsync
```

```bash
sudo dd if=nixos-installer-x86_64-linux.iso of=/dev/sdb bs=4M status=progress conv=fsync
```

## 6. Plug in and Run the Installer

Move the USB to the target, boot from it, and note the installer IP (LAN or WiFi) displayed. Pass it as `--target-host`; after installation the machine reboots with a different IP, configured in step 12. Secure Boot may need disabling: [secure boot instructions](../guides/secure-boot.md). If no IP appears and interfaces show `DOWN`, enable wireless in step 7.

```console
│ ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│ │Local network addresses:                                                         │ │
│ │enp1s0           UP    192.168.000.001/24 metric 1024 fe80::21e:6ff:fe45:3c92/64 │ │
│ │enp2s0           DOWN                                                            │ │
│ │wlan0            DOWN # connect to wlan (3)                                      │ │
│ │Onion address: 6evxy5yhzytwpnhc2vpscrbti3iktxdhpnf6yim6bbs25p4v6beemzyd.onion    │ │
│ │Multicast DNS: nixos-installer.local                                             │ │
│ └─────────────────────────────────────────────────────────────────────────────────┘ │
│ Press 'Ctrl-C' for console access
```

## 7. Enabling Wireless *During* Installation

Press Ctrl+C for a shell and run:

```bash
nmtui
```

In the GUI: Down Arrow → `Activate a Connection` → Enter; select the network used by the setup machine; Right Arrow → `\<Activate\>`; enter the password or push the router button; Esc → Down Arrow → `Quit`.

```bash
ping www.clan.lol
```

After connectivity succeeds, press **Ctrl+D** to return to the installer and note its IP for `--target-host`.

## 8. Configure SSH access

Authorize the setup key for this installer session only (not the USB; repeat after reboot). At the prompt, enter the root password shown on the installer:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<INSTALLER-IP>
```

```bash
ssh root@<INSTALLER-IP>
```

```console
[root@nixos-installer:~]#
```

## 9. Get Hardware Configuration

Replace `<INSTALLER-IP>` with the recorded installer IP; confirm with "y":

```bash
clan machines init-hardware-config test-machine --target-host root@<INSTALLER-IP>
```

## 10. Add a disk configuration

Run this first; it intentionally errors. Copy its disk ID (typically beginning `/dev/disk/by-id`) into `mainDisk`, then run the second command:

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk ""
```

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk "/dev/disk/by-id/..."
```

## 11. Install

Replace `<INSTALLER-IP>`; confirm with `y`; provide WiFi credentials (the setup machine's network) and a root password, or let Clan assign a random one:

```bash
clan machines install test-machine --target-host root@<INSTALLER-IP>
```

### If you get an error about Sandboxing

If sandboxing is unavailable, disable it and rerun installation. Re-enter WiFi credentials and root password if prompted:

```bash
clan vars generate test-machine --no-sandbox
```

```bash
clan machines install test-machine --target-host <USER>@<INSTALLER-IP>
```

Remove the USB before reboot; reboot manually if necessary.

## 12. Configure Access and Connect

After reboot, the installed system has a **new IP**; the installer IP is invalid. Find the new IP through router DHCP leases, or at the target console with `ip -4 addr`. Add it under `inventory.instances`:

```nix [clan.nix] {2-8}
  inventory.instances = { # FIND THIS LINE, ADD THE FOLLOWING
    internet = {
      roles.default.machines."test-machine" = {
        settings.host = "<MACHINE-IP>"; # REPLACE WITH THE INSTALLED MACHINE'S IP ADDRESS
        settings.user = "root";
      };
    };
```

`clan ssh` and `clan machines update` use this address:

```bash
clan ssh test-machine
```

If host identification fails, run the removal command shown by the error, similar to:

```bash
ssh-keygen -f '/home/user/.ssh/known_hosts' -R '<MACHINE-IP>'
```

```bash
clan ssh test-machine
```

```console
[root@test-machine:~]#
```

### Packages

Under `inventory.instances`, add:

```nix [clan.nix] {2-6}
  inventory.instances = {
    packages = {
      roles.default.machines."test-machine".settings = {
        packages = [ "bat" "btop" "tldr" ];
      };
    };
    # ... existing wifi service ...
  };
```

Apply and verify:

```bash
clan machines update test-machine
```

```bash
which bat
which btop
which tldr
```

```console
/run/current-system/sw/bin/bat
/run/current-system/sw/bin/btop
/run/current-system/sw/bin/tldr
```

Remove `"tldr"` from the declaration, update again, and verify it is absent:

```nix
packages = [ "bat" "btop" ];
```

```bash
clan machines update test-machine
```

```console
which tldr
which: no tldr in (/run/wrappers/bin:/root/.nix-profile/bin:/nix/profile/bin:/root/.local/state/nix/profile/bin:/etc/profiles/per-user/root/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin)

```

## Practice: Configuring Users

### Add a New User (no sudo access)

Under `inventory.instances`, add Alice:

```nix [clan.nix] {2-9}
  inventory.instances = { # Add the following under this line
    user-alice = {
      module.name = "users";
      roles.default.machines."test-machine" = {};
      roles.default.tags = [ "all" ];
      roles.default.settings = {
        user = "alice";
      };
    };
```

Generate Alice's password; include `--no-sandbox` if sandboxing was previously disabled. Enter a password, or press Enter to generate one. Retrieve an automatically generated password with:

```bash
clan vars generate test-machine --no-sandbox
```

```bash
clan vars get test-machine user-password-alice/user-password
```

Then update; Alice can log in on the target with that password:

```bash
clan machines update test-machine
```

### Give that user sudo access

After trusting Alice, add her to `wheel`, update, and log out/in again if she was already logged in:

```nix [clan.nix] {7}
    user-alice = {
      module.name = "users";
      roles.default.machines."test-machine" = {};
      roles.default.tags = [ "all" ];
      roles.default.settings = {
        user = "alice";
        groups = [ "wheel" ];  # Add this to allow sudo
      };
    };
```

```bash
clan machines update test-machine
```

```bash
sudo echo "hello"
```

The password prompt should be followed by `hello`.

### Revoke the sudo access

Remove the `wheel` line, update, log Alice out and back in, then retry sudo:

```nix
        groups = [ "wheel" ];

```

```bash
clan machines update test-machine
```

```console
alice is not in the sudoers file.
```
