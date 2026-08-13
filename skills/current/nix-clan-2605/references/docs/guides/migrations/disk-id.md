# Disk Id

## Migrate `clanModules.disk-id` to standalone disko

For machines bootstrapped with `clanModules.disk-id`, migrate to a self-contained `disko.nix`: static values improve long-term stability and remove dependence on Clan-generated values.

**Safety:** DO NOT EDIT `disko.nix` AFTER MACHINE INSTALLATION; missing partitions/filesystems may prevent boot.

### 1. Retrieve the generated disk ID

```bash
clan vars list $MACHINE_NAME
```

Output includes the clear-text `disk-id/diskId`; copy its value:

```console
disk-id/diskId: fcef30a749f8451d8f60c46e1ead726f
```

### 2. Make `disko.nix` static

For an existing configuration using the `diskId` module:

- Remove the `let ... in` expression, module-function arguments (`{lib, clan-core, config, ...}:`), and `imports`.
- Replace dynamic `suffix` with the copied disk ID.
- Move `disko.devices.disk.main.device` from `flake.nix` or `configuration.nix` into `disko.nix`.

```nix [disko.nix] {7-9,11-14}
{
  boot.loader.grub.efiSupport = lib.mkDefault true;
  boot.loader.grub.efiInstallAsRemovable = lib.mkDefault true;
  disko.devices = {
    disk = {
      "main" = {
        #       ↓ Copy the disk-id into place
        name = "main-fcef30a749f8451d8f60c46e1ead726f";
        type = "disk";

        # Some earlier guides had this line in a flake.nix
        # disko.devices.disk.main.device = "/dev/disk/by-id/CHANGE_ME";
        #        ↓ Copy the '/dev/disk/by-id' into here instead
        device = "/dev/disk/by-id/nvme-eui.e8238fa6bf530001001b448b4aec2929";
      };
    };
  };
}
```

Newer machines can use Clan disk templates via the [templates CLI](https://clan.lol/docs/26.05/reference/cli/templates).
