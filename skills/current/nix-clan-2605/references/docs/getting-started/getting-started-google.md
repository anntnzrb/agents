# Getting Started: Google Cloud Edition

:::admonition[Prerequisites]{type=note}
Setup machine requires:

* **Nix**, unless setup machine runs NixOS. See [Install Nix and direnv](install-nix.md).
* An **id_ed25519** keypair. (Link coming soon.)
* **Git** optional; Clan uses Git internally. See [Git installation instructions](https://git-scm.com/install/linux).
:::

## Step 1. Create a Server on Google Cloud

:::admonition[Danger]{type=danger}
These steps erase all data on the Google Cloud server's hard drive.
:::

Skip if a Google Cloud server already exists. `gcloud` recommended:

```text
gcloud compute instances create linux-server-01 \
    --machine-type=e2-medium \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --metadata="ssh-keys=$(whoami):$(cat ~/.ssh/id_ed25519.pub)" \
    --no-shielded-secure-boot \
    --no-shielded-vtpm \
    --no-shielded-integrity-monitoring
```

`whoami` creates a remote user matching the local username. Find the actual IP under `EXTERNAL_IP` in the output:

```text
NAME             ZONE           MACHINE_TYPE  PREEMPTIBLE  INTERNAL_IP  EXTERNAL_IP  STATUS
linux-server-01  us-central1-a  e2-medium                  10.128.0.4   34.170.5.83  RUNNING
```

After boot (possibly requiring retries), verify login, replacing placeholders:

```bash
ssh <USERNAME>@<IP-ADDRESS>
```

Enable root access:

```bash
gcloud compute ssh linux-server-01 --command="sudo mkdir -p /root/.ssh && sudo cp ~/.ssh/authorized_keys /root/.ssh/authorized_keys"
```

```bash
gcloud compute ssh linux-server-01 --command="sudo sed -i 's/PermitRootLogin no/PermitRootLogin prohibit-password/g' /etc/ssh/sshd_config"
```

```bash
gcloud compute ssh linux-server-01 --command="sudo systemctl restart ssh"
```

Test root access, replacing `<IP-ADDRESS>`:

```bash
ssh root@<IP-ADDRESS>
```

```bash
exit
```

## Step 2. Run the Clan setup

```text
nix run https://clan.lol/install/26.05 --refresh -- init
```

Enter a clan name (for example, `MY-CLAN-1`) and domain (for example, `myclan1.lol`; it need not be registered).

First run: Clan creates the age key `~/.config/sops/age/keys.txt` for secret encryption. Back it up safely, then type `y`. If setup ran before, select admin keys; usually type `1`, Enter.

```bash
cd MY-CLAN-1
direnv allow
```

## Step 3. Create a Machine Configuration

```bash
clan machines create test-machine
```

In `clan.nix`, immediately after `inventory.machines`:

```nix [clan.nix] {2,3,4,5}
inventory.machines = { # FIND THIS LINE, ADD THE FOLLOWING
    test-machine = {
        tags = [ "test" ];
    };
```

Farther down, under `inventory.instances`, replace the host IP:

```nix [clan.nix] {2-8}
  inventory.instances = { # FIND THIS LINE, ADD THE FOLLOWING
    internet = {
      roles.default.machines."test-machine" = {
        settings.host = "<IP-ADDRESS>"; # REPLACE WITH YOUR MACHINE'S IP ADDRESS
        settings.user = "root";
      };
    };
```

```bash
clan machines list
```

## Step 4. Add your allowed keys

```bash
cat ~/.ssh/id_ed25519.pub
```

In `clan.nix`, replace `PASTE_YOUR_KEY_HERE` with that file's contents:

```text
"admin-machine-1" = "PASTE_YOUR_KEY_HERE";
```

```bash
clan show
```

## Step 5. Gather Hardware Configuration

```bash
clan machines init-hardware-config test-machine
```

Confirm with `y`.

## Step 6. Add a Disk Configuration

Run once; it intentionally errors. Copy the printed disk ID, typically `/dev/disk/by-id/scsi-0Google_PersistentDisk_persistent-disk-0`, into the second command:

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk ""
```

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk "/dev/disk/by-id/scsi-0Google_PersistentDisk_persistent-disk-0"
```

Google Cloud does not expose partition tables to the guest OS. Adjust the generated `configuration.nix` and `disko.nix`:

```bash
cd machines/test-machine
```

Replace `configuration.nix` with:

```nix
{ lib, modulesPath, ... }:
{
  imports = [
    (modulesPath + "/virtualisation/google-compute-image.nix")
  ];
  networking.hostName = lib.mkForce "test-machine";
  security.googleOsLogin.enable = lib.mkForce false;
}
```

`google-compute-image.nix` supplies Google Cloud drivers/services but enables Google OS Login, which conflicts with Clan's `sshd`/`authorized_keys`; `lib.mkForce false` overrides the module's value.

In `disko.nix`, add the highlighted lines. Changes to this generated configuration wipe and reinstall the machine:

```nix [disko.nix] {8,14,15,39,48}
# ---
# schema = "ext4-single-disk"
# [placeholders]
# mainDisk = "/dev/disk/by-id/scsi-0Google_PersistentDisk_persistent-disk-0"
# ---
# This file was automatically generated!
# CHANGING this configuration requires wiping and reinstalling the machine
{ lib, ... }: # ADD THIS LINE
{
  boot.loader.grub = {
    efiInstallAsRemovable = true;
    efiSupport = true;
  };
  boot.loader.timeout = lib.mkForce 0; # ADD THIS LINE
  fileSystems."/".device = lib.mkForce "/dev/disk/by-label/nixos"; # ADD THIS LINE

  disko.devices = {
    disk = {
      main = {
        name = "main-49086db16eb74c23bed59fc2045fd513";
        device = "/dev/disk/by-id/scsi-0Google_PersistentDisk_persistent-disk-0";
        type = "disk";
        content = {
          type = "gpt";
          partitions = {
            "boot" = {
              size = "1M";
              type = "EF02"; # for grub MBR
              priority = 1;
            };
            ESP = {
              type = "EF00";
              size = "500M";
              content = {
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot";
                mountOptions = [ "umask=0077" ];
                extraArgs = [ "-n" "ESP" ]; # ADD THIS LINE
              };
            };
            root = {
              size = "100%";
              content = {
                type = "filesystem";
                format = "ext4";
                mountpoint = "/";
                extraArgs = [ "-L" "nixos" ]; # ADD THIS LINE
              };
            };
          };
        };
      };
    };
  };
}
```

```bash
cd ../..
```

## Step 7. Install NixOS

```bash
clan machines install test-machine
```

Confirm installation with `y`. For the installation password, accept defaults with Enter. For the machine's root-login password, create one or let Clan generate a random one.

### If you get an error about Sandboxing

```bash
clan vars generate test-machine --no-sandbox
```

Then rerun `clan machines install test-machine`.

## Step 8. Test the Connection

```bash
clan ssh test-machine
```

An initial host-identification error may show a command removing the old ID. Paste the displayed command, similar to:

```text
  ssh-keygen -f '/home/user/.ssh/known_hosts' -R '<IP-ADDRESS>'
```

Retry:

```bash
clan ssh test-machine
```

Successful login shows a prompt such as:

```text
[root@test-machine:~]#
```

## Practice: Install Some Packages

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

```bash
clan machines update test-machine
```

SSH into the machine and verify:

```text
which bat
which btop
which tldr
```

Expected paths:

```text
/run/current-system/sw/bin/bat
/run/current-system/sw/bin/btop
/run/current-system/sw/bin/tldr
```

To remove `tldr`, change the declaration:

```text
        packages = [ "bat" "btop" ];
```

Then update again:

```bash
clan machines update test-machine
```

`which tldr` should report it absent:

```text
which tldr
which: no tldr in (/run/wrappers/bin:/root/.nix-profile/bin:/nix/profile/bin:/root/.local/state/nix/profile/bin:/etc/profiles/per-user/root/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin)

```

## Practice: Configuring Users

### Add a New User (no sudo access)

Under `inventory.instances` in `clan.nix`, add Alice:

```nix [clan.nix] {2-9}
  inventory.instances = { # Add the following under this line
    user-alice = {
      module.name = "users";
      roles.default.machines."test-machine" = {};
      roles.default.tags.all = {};
      roles.default.settings = {
        user = "alice";
      };
    };
```

Generate Alice's password; include `--no-sandbox` if sandboxing previously required it:

```bash
clan vars generate test-machine --no-sandbox
```

Enter a password or press Enter to generate one. Retrieve an automatically generated password with:

```text
clan vars get test-machine user-password-alice/user-password
```

On cloud machines, this password is used for sudo if granted; password login is typically disabled.

Get your public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

In `machines/test-machine/configuration.nix`, before the closing brace, add the following and replace `PASTE_YOUR_KEY_HERE`:

```nix [machines/test-machine/configuration.nix] {8-10}
{
  imports = [

  ];

  # New machine!

  users.users.alice.openssh.authorizedKeys.keys = [
    "PASTE_YOUR_KEY_HERE"
  ];
}
```

Update and connect:

```bash
clan machines update test-machine
ssh alice@<IP-ADDRESS>
```

Replace `<IP-ADDRESS>` with the Google Cloud server IP.

### Give that user sudo access

Add Alice to `wheel` in `clan.nix`:

```nix [clan.nix] {7}
    user-alice = {
      module.name = "users";
      roles.default.machines."test-machine" = {};
      roles.default.tags.all = {};
      roles.default.settings = {
        user = "alice";
        groups = [ "wheel" ];  # Add this to allow sudo
      };
    };
```

```bash
clan machines update test-machine
```

If already logged in as Alice, log out and back in. Then:

```bash
sudo echo "hello"
```

Enter the password; `hello` should print.

### Revoke the sudo access

Remove the `groups` line:

```nix
        groups = [ "wheel" ];
```

Update and re-login:

```bash
clan machines update test-machine
```

Log Alice out and back in. The same command now prompts for a password and displays:

```text
alice is not in the sudoers file.
```
