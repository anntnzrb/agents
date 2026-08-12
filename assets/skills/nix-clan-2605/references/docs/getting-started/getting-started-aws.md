# Getting Started: AWS

:::admonition[Prerequisites]{type=note}
Setup Machine: **Nix** (unless NixOS), an **id_ed25519** keypair, and optionally **Git**. See [Install Nix and direnv](install-nix.md) and [Git installation instructions](https://git-scm.com/install/linux).
:::

## 1. Create an AWS Server

:::admonition[Danger]{type=danger}
These steps erase all data on the AWS server's hard drive.
:::

AWS Console → EC2 → **Instances** → **Launch Instances**. Name it, e.g. `Clan Test Machine`. **Application and OS Images** → **Quick Start** → **Ubuntu**. Choose at least **t3-small**; **t3-large** works best.

:::admonition[Note]{type=note}
Do not use t2. Prefer Nitro types (`t3`, `m5`, `c5`, `r5`, `m6i`, `c6i`, etc.); avoid Xen types (`t2`, `m4`, `c4`, `r4`, etc.), because Clan's newer kexec tool does not work well with Amazon's Xen infrastructure changes.
:::

**Key pair**: select an existing pair or create an **ED25519** pair; move a downloaded new key to `~/.ssh`. **Network Settings**: create/use a security group allowing SSH from at least your IP. **Configure Storage**: `16` GB. Click **Launch instance**.

After it runs, verify access (`ubuntu` is Ubuntu EC2's main username):

```bash
ssh -i <KEY-PAIR-FILE> ubuntu@<IP-ADDRESS>
```

`<KEY-PAIR-FILE>` = key path/name; `<IP-ADDRESS>` = server public IP (EC2 instance ID → near the console's upper middle). Then:

```bash
exit
```

## 2. Add the `id_ed25519` Key Pair

MUST do this: Clan connects using an existing `id_ed25519` key. From the local machine:

```bash
ssh -i ~/.ssh/<KEY-PAIR-FILE>.pem ubuntu@<IP-ADDRESS> \
"cat >> /home/ubuntu/.ssh/authorized_keys" < ~/.ssh/id_ed25519.pub
```

`<KEY-PAIR-FILE>` = provisioning key filename. Verify keyless access, then exit:

```text
ssh ubuntu@<IP-ADDRESS>
```

```bash
exit
```

## 3. Set Up Clan

Create a clan, then enter a name (e.g. `MY-CLAN-1`) and domain (e.g. `myclan1.lol`; it need not be registered):

```text
nix run https://clan.lol/install/26.05 --refresh -- init
```

First run: Clan creates the age key `~/.config/sops/age/keys.txt` for secret encryption; back it up safely, then type `"y"`. If setup ran before, select admin keys, usually `"1"` then Enter.

```bash
cd MY-CLAN-1
direnv allow
```

## 4. Create Machine Configuration

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

Farther down, add this and replace `<IP-ADDRESS>` with the AWS server IP:

```nix [clan.nix] {2-8}
  inventory.instances = { # FIND THIS LINE, ADD THE FOLLOWING
    internet = {
      roles.default.machines."test-machine" = {
        settings.host = "<IP-ADDRESS>"; # REPLACE WITH YOUR MACHINE'S IP ADDRESS
        settings.user = "root";
      };
    };
```

`settings.user = "root"` is required because Clan uses `root` after booting NixOS, although Ubuntu uses `ubuntu` before boot.

```bash
clan machines list
```

## 5. Add Allowed Keys

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

## 6. Gather Hardware Configuration

Use `ubuntu` for this pre-NixOS connection:

```bash
clan machines init-hardware-config test-machine --target-host ubuntu@<IP-ADDRESS>
```

Confirm with `"y"`. Repeated `"Connection timed out"` messages can occur while the server reboots; wait for reconnection.

## 7. Configure Disk

Run once; the intentional error prints the disk ID (typically beginning `/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_`):

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk ""
```

Insert that ID between the quotes and rerun, e.g.:

```bash
clan templates apply disk ext4-single-disk test-machine --set mainDisk "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_113572628"
```

## 8. Install NixOS

```bash
clan machines install test-machine
```

Confirm installation with `y`; password prompts accept defaults with Enter. Set a root-login password or let Clan generate a random one.

### Sandboxing failure

If sandboxing is unavailable, disable it and rerun the install command:

```bash
clan vars generate test-machine --no-sandbox
```

## 9. Test Connection

```bash
clan ssh test-machine
```

On an initial host-identification error, run the displayed removal command (similar to):

```text
  ssh-keygen -f '/home/user/.ssh/known_hosts' -R '<IP-ADDRESS>'
```

Retry:

```bash
clan ssh test-machine
```

Expected prompt:

```text
[root@test-machine:~]#
```

## Practice: Packages

Under `inventory.instances` in `clan.nix`, declare `bat`, `btop`, and `tldr`:

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

Update and verify:

```bash
clan machines update test-machine
```

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

Remove `"tldr"` from the package declaration; Nix removes it on update:

```text
        packages = [ "bat" "btop" ];
```

```bash
clan machines update test-machine
```

Then `which tldr` reports:

```text
which tldr
which: no tldr in (/run/wrappers/bin:/root/.nix-profile/bin:/nix/profile/bin:/root/.local/state/nix/profile/bin:/etc/profiles/per-user/root/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin)

```

## Practice: Users

Add users in `clan.nix`, then update the machine.

### Add Alice without sudo

Under `inventory.instances` in `clan.nix`:

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

Generate Alice's password; include `--no-sandbox` if sandboxing required it earlier. Enter a password, or press Enter to generate one:

```bash
clan vars generate test-machine --no-sandbox
```

Retrieve an automatically generated password:

```text
clan vars get test-machine user-password-alice/user-password
```

:::admonition[Note]{type=note}
On cloud machines, this password is used for sudo if granted; password login is typically disabled.
:::

Get the public key and put it in `machines/test-machine/configuration.nix` before the closing brace, replacing `PASTE_YOUR_KEY_HERE`:

```bash
cat ~/.ssh/id_ed25519.pub
```

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

Update, then connect as Alice:

```bash
clan machines update test-machine
```

```bash
ssh alice@<IP-ADDRESS>
```

Replace `<IP-ADDRESS>` with the AWS server IP.

### Grant Alice sudo

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

If Alice was logged in during the update, log out and back in. Her password should authenticate:

```bash
sudo echo "hello"
```

Expected output: `hello`.

### Revoke Alice's sudo

Remove the `wheel` line:

```nix
        groups = [ "wheel" ];

```

Update, log Alice out and back in, then retry:

```bash
clan machines update test-machine
```

```text
alice is not in the sudoers file.
```
