# NixOS specialisations

Named system-configuration variants; each produces a separate system closure, selectable at boot or runtime without rebuilding. Best for a small number of pre-defined variants sharing most configuration: GPU drivers, desktop environments, kernel parameters, or grouped options.

## Defining specialisations

Add `specialisation`; each entry names a variant and supplies differing NixOS module options.

```nix
{ lib, ... }:
{
  # Base configuration: GNOME desktop, no Nvidia drivers
  services.xserver.desktopManager.gnome.enable = true;
  hardware.nvidia.modesetting.enable = lib.mkDefault false;

  specialisation = {
    nvidia.configuration = {
      hardware.nvidia.modesetting.enable = true;
      hardware.nvidia.open = true;
      services.xserver.videoDrivers = [ "nvidia" ];
    };

    plasma.configuration = {
      services.xserver.desktopManager.plasma5.enable = true;
    };
  };
}
```

Each specialisation inherits the full parent configuration and layers its options on top; `nvidia` adds Nvidia drivers, while `plasma` adds Plasma alongside GNOME. Both become separate boot entries after rebuilding.

:::admonition[Overriding parent values]{type=tip}
Specialisations inherit the parent by default. If a specialisation must change a parent value, mark the parent value with `lib.mkDefault`; this lets the specialisation override it without priority conflicts. Example: `hardware.nvidia.modesetting.enable = lib.mkDefault false;` permits `nvidia` to set it to `true`.
:::

## Starting independently with `inheritParentConfig`

Default: every specialisation inherits the parent. For an independent system, set `inheritParentConfig = false`:

```nix
specialisation = {
  minimal = {
    inheritParentConfig = false;
    configuration = {
      system.nixos.tags = [ "minimal" ];
      boot.loader.grub.enable = true;
      fileSystems."/" = { device = "/dev/sda1"; fsType = "ext4"; };
      # ... everything else must be specified explicitly
    };
  };
};
```

Useful for stripped-down recovery or fundamentally different variants. With `inheritParentConfig = false`, `configuration` MUST specify a complete, bootable NixOS system.

## Excluding options from specialisations

To apply an option only to the default (non-specialised) entry, guard it with `config.specialisation != {}`:

```nix
{
  lib,
  config,
  pkgs,
  ...
}:
{
  config = lib.mkIf (config.specialisation != { }) {
    # Only applies to the default system, not to specialisations
    hardware.graphics.extraPackages = with pkgs; [
      vaapiIntel
      vaapiVdpau
    ];
  };
}
```

:::admonition[Condition requires specialisations]{type=warning}
`config.specialisation != {}` evaluates to `false` when no specialisations exist; the conditional takes effect only when at least one exists.
:::

## Activating at boot

After `clan machines update` or `nixos-rebuild switch`, each specialisation appears as a separate bootloader entry; select one at boot.

## Switching at runtime with Clan

Use `--specialisation` with `clan machines update`:

```bash
clan machines update my-machine --specialisation nvidia
```

This builds and activates the named specialisation on the target; its `switch-to-configuration switch` script applies it without rebooting.

:::admonition[Runtime limitations]{type=warning}
Not all changes apply at runtime. A different kernel, for example, does not replace the running kernel until reboot; reboot and select the specialisation from the boot menu.
:::

On the target machine:

```bash
sudo nixos-rebuild switch --specialisation nvidia
```

## When to use specialisations

Typical variants:

- GPU driver toggles (enable/disable proprietary drivers)
- Desktop environment alternatives (GNOME vs. Plasma)
- Performance profiles (power-saving vs. high-performance kernel parameters)
- Debug configurations (verbose logging, extra diagnostic tools)

For more granular or independently composable differences, NixOS module options with `lib.mkDefault` and `lib.mkForce` may fit better.
