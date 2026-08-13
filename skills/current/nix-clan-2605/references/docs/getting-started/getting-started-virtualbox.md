# Getting Started: VirtualBox

:::admonition[Prerequisites]{type=note collapsible}
Setup machine requirements:

* VirtualBox ([official downloads](https://www.virtualbox.org/wiki/Downloads)).
* **Nix** or **NixOS**; see [Install Nix and direnv](install-nix.md).
* An **id_ed25519** [keypair file](create-an-ssh-key.md).
* Git optional; Clan uses Git internally. See [Git installation](https://git-scm.com/install/linux).
:::

:::admonition[Tip]{type=tip}
Linux, preferably NixOS, recommended for setup. Windows with WSL is not recommended: significantly slower; install may freeze during package downloads.
:::

## 1. Download the ISO

* X86_64: [nixos-installer-x86_64-linux.iso](https://github.com/nix-community/nixos-images/releases/download/nixos-26.05/nixos-installer-x86_64-linux.iso)
* AArch64: [nixos-installer-aarch64-linux.iso](https://github.com/nix-community/nixos-images/releases/download/nixos-26.05/nixos-installer-aarch64-linux.iso)

## 2. Create and run the VirtualBox machine

In VirtualBox, click **New**:

1. Name: `NixOS Installer`; leave **Folder** default.
2. **ISO Image** → **Other** → select the downloaded `nixos-installer-x86_64-linux.iso` or `nixos-installer-aarch64-linux.iso` → **Open**; continue with **Next**.
3. Depending on UI version:
   * **Type**: **Linux**; **Version**: **Linux 2.6 / 3.x / 4.x / 5.x (64-bit)**.
   * **OS**: **Linux**; **OS Distribution**: **Other Linux**; **OS Version**: **Other Linux (64-bit)**.
4. **Next** or **Specify virtual hardware**: **Base Memory** `8192`, **Processors** at least `3` when available; leave **Enable EFI (special OSes only)** unchecked; **Next**.
5. **Virtual Hard Disk** or **Specify virtual hard disk** → **Create a Virtual Hard Disk Now** → size `20` GB → **Next** if present → **Finish**.
6. **Do not run the machine yet.** Right-click **NixOS Installer** → **Settings** → **Network** → **Adapter 1** → **Attached to**: **Bridged Adapter**; leave **Name** unchanged → **OK**.

Select the VM → **Start**. Wait for the NixOS loader and screen beginning with a QR code. Record the installer root password under **Login Credentials** and the IP under **Network Information** (for example `10.0.0.18`). Use the IP, not the **Remote Access** hostname: the hostname stops working after installation.

:::admonition[Tip]{type=tip}
If VM output obscures the IP, press **Ctrl+C**, then **Ctrl+D**, and wait for refresh.
:::

## 3. Initialize Clan

Create a clan:

```bash
nix run https://clan.lol/install/26.05 --refresh -- init
```

Enter a clan name, for example `MY-CLAN-1`, and domain, for example `myclan1.lol`; the domain need not be registered.

:::admonition[Important]{type=note}
First run creates the secret-encrypting age key at `~/.config/sops/age/keys.txt`; back it up safely, then type "y". If Clan was run before, select admin keys, usually `1` then Enter.
:::

```bash
cd MY-CLAN-1
```

Approve direnv:

```bash
direnv allow
```

Create the machine:

```text
clan machines create test-machine
```

Immediately after `inventory.machines` in `clan.nix`, add:

```nix [clan.nix] {2,3,4,5}
inventory.machines = { # FIND THIS LINE, ADD THE FOLLOWING
    test-machine = {
        tags = [ "test" ];
    };
```

Check the machine, add the setup machine's public key to the allowed keys, and validate:

```bash
clan machines list
```

```bash
cat ~/.ssh/id_ed25519.pub
```

Replace `PASTE_YOUR_KEY_HERE` with the contents of `id_ed25519.pub`:

```nix
"admin-machine-1" = "PASTE_YOUR_KEY_HERE";
```

```bash
clan show
```

Replace `<INSTALLER-IP>` with the installer-screen IP (for example `10.0.0.18`). At the prompt, enter the QR-screen root password:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<INSTALLER-IP>
```

Confirm login, then exit the SSH session before running the next command locally:

```bash
ssh root@<INSTALLER-IP>
```

Gather hardware configuration:

```bash
clan machines init-hardware-config test-machine --target-host root@<INSTALLER-IP>
```

Confirm with `"y"`.

## 4. Configure disk and install

Run first with an empty disk value; it intentionally errors. Record the printed disk ID (typically beginning `/dev/disk/by-id/ata-VBOX_HARDDISK_VB`) and substitute it for the empty quotes:

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk ""
```

Example:

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk "/dev/disk/by-id/ata-VBOX_HARDDISK_VB21917326-250e62d3"
```

Install:

```bash
clan machines install test-machine --target-host root@<INSTALLER-IP>
```

Confirm with `y`; accept password defaults with Enter. Set a root-login password or let Clan generate one.

If sandboxing is unavailable:

```bash
clan vars generate test-machine --no-sandbox
```

Then rerun the install command. If a secret does not exist, rerun the **vars generate** command.

## 5. Remove ISO and reboot

Shut down via VM close **X** → **Send the shutdown signal** → **OK**. If unavailable, choose **Power off the machine**. Right-click VM → **Settings...** → **Storage**. Under **Controller: IDE**, select the mounted `.iso`; click the CD-ROM image beside **Optical Drive: IDE Secondary Device 0** → **Remove Disk from Virtual Drive** → **OK**.

Start the VM again. At:

```console
test-machine login:
```

Log in as `root` with the installation password and run:

```bash
ip addr
```

The installed system has a **new IP address**; the installer IP is invalid. Replace `<MACHINE-IP>` below with the new address and add this after `inventory.instances` in `clan.nix`:

```nix [clan.nix] {2-8}
  inventory.instances = { # FIND THIS LINE, ADD THE FOLLOWING
    internet = {
      roles.default.machines."test-machine" = {
        settings.host = "<MACHINE-IP>"; # REPLACE WITH THE INSTALLED MACHINE'S IP ADDRESS
        settings.user = "root";
      };
    };
```

`clan ssh` and `clan machines update` use this address.

```bash
clan ssh test-machine
```

The first connection may report stale host identification. Run the displayed removal command, similar to:

```bash
ssh-keygen -f '/home/user/.ssh/known_hosts' -R '<MACHINE-IP>'
```

Then retry:

```bash
clan ssh test-machine
```

Expected prompt:

```console
[root@test-machine:~]#
```

## Packages

Under `inventory.instances` in `clan.nix`, add:

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

The list declares additional packages present on the machine. Apply and verify:

```bash
clan machines update test-machine
```

```bash
which bat
which btop
which tldr
```

Expected paths:

```console
/run/current-system/sw/bin/bat
/run/current-system/sw/bin/btop
/run/current-system/sw/bin/tldr
```

Remove `"tldr"` from `clan.nix`, then update:

```nix
packages = [ "bat" "btop" ];
```

```bash
clan machines update test-machine
```

`which tldr` should report:

```console
which tldr
which: no tldr in (/run/wrappers/bin:/root/.nix-profile/bin:/nix/profile/bin:/root/.local/state/nix/profile/bin:/etc/profiles/per-user/root/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin)

```

## Practice: users

### Add Alice without sudo

Under `inventory.instances` in `clan.nix`, add:

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

Save the file. Generate Alice's password. If sandboxing was disabled earlier, use:

```bash
clan vars generate test-machine --no-sandbox
```

Otherwise omit `--no-sandbox`. Enter a password, or press Enter for automatic generation. Retrieve an automatically generated password with:

```bash
clan vars get test-machine user-password-alice/user-password
```

```bash
clan machines update test-machine
```

Alice can log in to the VM after the update.

### Grant sudo

After trusting Alice, add her to `wheel`:

```nix [clan.nix] {7}
    user-alice = {
      module.name = "users";
      roles.default.machines."test-machine" = {};
      roles.default.tags = [ "all" ];
      roles.default.settings = {
        user = "alice";
        groups = [ "wheel" ];  # Add this to allow sudo // [!code ++]
      };
    };
```

```bash
clan machines update test-machine
```

If Alice was logged in during the update, log out and back in first. Then run:

```bash
sudo echo "hello"
```

Sudo prompts for the password and prints `hello`.

### Revoke sudo

Remove the `groups = [ "wheel" ];` line (marked `[!code --]` below):

```nix [clan.nix] {7}
    user-alice = {
      module.name = "users";
      roles.default.machines."test-machine" = {};
      roles.default.tags = [ "all" ];
      roles.default.settings = {
        user = "alice";
        groups = [ "wheel" ];  # Remove this to revoke sudo // [!code --]
      };
    };
```

```bash
clan machines update test-machine
```

Log out and back in as Alice, then run:

```bash
sudo echo "hello"
```

After the password prompt, expected output:

```console
alice is not in the sudoers file.
```
