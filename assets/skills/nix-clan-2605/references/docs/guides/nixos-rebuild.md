# NixOS rebuild with Clan

`nixos-rebuild` remains supported: Clan builds on standard NixOS and uses it internally. Direct use differs from `clan machines update`.

## Direct `nixos-rebuild`

- Vars present: MUST run `clan vars upload <machine>` first; otherwise secrets may be missing and services may break.
- MUST specify `--build-host` and `--target-host` manually. Clan derives build-host configuration from machine settings during `clan machines update`.

Vars include generated secrets, keys, or configuration values from `clanServices` (for example, zerotier and borgbackup), custom generators, and shared service configuration. Vars are unnecessary for basic configurations without Clan-specific services, static hardcoded values, or traditional NixOS secrets management.

## Manual workflow

### Step 1: Upload vars (if needed)

```bash
# Upload secret vars to the target device
clan vars upload my-machine
```

### Step 2: Run nixos-rebuild

```bash
nixos-rebuild switch --flake .#my-machine --target-host root@target-ip --build-host local
```

## `clan machines update` sequence

1. Generate and upload secrets/vars, if any.
2. Upload flake source to target/build host, if needed.
3. Build NixOS system closure.
4. Set system profile with `nix-env --set`.
5. Run `switch-to-configuration boot` to register the generation in the bootloader.
6. Run `switch-to-configuration switch` to live-activate it.
7. If switch inhibitors block live activation (for example, critical `dbus` or `systemd` changes), report failure and suggest rebooting; the configuration is already registered for next boot.

`--no-check` or `NIXOS_NO_CHECK=1` forces past switch inhibitors; use only when live switching is known safe.
