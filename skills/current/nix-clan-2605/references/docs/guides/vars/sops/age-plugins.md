# Age plugins for Clan Vars

`clan vars` uses `age` by default; `age` supports plugins.

## Supported plugins

Popular [`age` plugins](https://github.com/FiloSottile/awesome-age?tab=readme-ov-file#plugins) usable with Clan (updated **September 12, 2025**):

- ⭐️ [**age-plugin-yubikey**](https://github.com/str4d/age-plugin-yubikey): YubiKey and other PIV tokens; official.
- [**age-plugin-se**](https://github.com/remko/age-plugin-se): Apple Secure Enclave.
- 🧪 [**age-plugin-tpm**](https://github.com/Foxboron/age-plugin-tpm): TPM 2.0.
- 🧪 [**age-plugin-tkey**](https://github.com/quite/age-plugin-tkey): Tillitis TKey.
- [**age-plugin-trezor**](https://github.com/romanz/trezor-agent/blob/master/doc/README-age.md): hardware wallets (TREZOR, Ledger, etc.).
- 🧪 [**age-plugin-sntrup761x25519**](https://github.com/keisentraut/age-plugin-sntrup761x25519): post-quantum hybrid (NTRU Prime + X25519).
- 🧪 [**age-plugin-fido**](https://github.com/riastradh/age-plugin-fido): prototype symmetric encryption for FIDO2 keys.
- 🧪 [**age-plugin-fido2-hmac**](https://github.com/olastor/age-plugin-fido2-hmac): FIDO2 with PIN support.
- 🧪 [**age-plugin-sss**](https://github.com/olastor/age-plugin-sss): Shamir's Secret Sharing (SSS).
- 🧪 [**age-plugin-amnesia**](https://github.com/cedws/amnesia/blob/master/README.md#age-plugin-experimental): Q&A-based identity wrapping.

⭐️ official; 🧪 experimental.

## Plugin-generated keys

To encrypt with `fido2 tokens` instead of a normal age secret key, prefix the key with the plugin name: replace `AGE-SECRET-KEY` with `AGE-PLUGIN-FIDO2-HMAC`.

:::admonition[Tip]{type=tip collapsible}

- Linux: `~/.config/sops/age/keys.txt`
- macOS: `/Users/admin/Library/Application Support/sops/age/keys.txt`
:::

**Before**:

```text {2}
# public key: age1zdy49ek6z60q9r34vf5mmzkx6u43pr9haqdh5lqdg7fh5tpwlfwqea356l
AGE-SECRET-KEY-1QQPQZRFR7ZZ2WCV...
```

**After**:

```text {2}
# public key: age1zdy49ek6z60q9r34vf5mmzkx6u43pr9haqdh5lqdg7fh5tpwlfwqea356l
AGE-PLUGIN-FIDO2-HMAC-1QQPQZRFR7ZZ2WCV...
```

## Configure `flake.nix`

Configure plugins in `flake.nix`. Each `secrets.age.plugins` entry is either a nixpkgs package name (for example, `"age-plugin-yubikey"`) or a flake reference for a package absent from nixpkgs (for example, `"github:owner/repo#package"`).

```nix [flake.nix]
{
  inputs.clan-core.url = "https://git.clan.lol/clan/clan-core/archive/26.05.tar.gz";
  inputs.nixpkgs.follows = "clan-core/nixpkgs";

  outputs =
    { self, clan-core, ... }:
    let
      # Define Clan configuration
      clan = clan-core.lib.clan {
        inherit self;

        meta.name = "myclan";
        meta.domain = "ccc";

        # Add age plugins
        secrets.age.plugins = [
          # Plugins available in nixpkgs can be specified by name
          "age-plugin-yubikey"
          "age-plugin-fido2-hmac"
          # Plugins not in nixpkgs can be specified as flake references
          "github:pinpox/age-plugin-picohsm#default"
        ];

        machines = {
          # Machine configurations (omitted for brevity)
        };
      };
    in
    {
      inherit (clan) nixosConfigurations nixosModules clanInternals;

      # Additional configurations (omitted for brevity)
    };
}
```
