# age Backend for Vars

The **age** backend encrypts secrets with [age](https://github.com/FiloSottile/age), stores and uploads only ciphertext, and decrypts on the target during NixOS activation; plaintext exists only in target memory.

## Choose a Backend

Use age for direct age encryption without sops, target-side decryption without the sops-nix Go binary, automatic machine-key management, or hardware-token identities (YubiKey, PicoHSM) through age plugins. Use the [SOPS backend](../sops/secrets) for an existing sops workflow or sops-nix systemd service integration.

## Key Model

Each machine has an age keypair. Its private key is encrypted to user key(s); secrets are encrypted to machine public keys, not user keys. Deployment uploads the decrypted machine private key plus encrypted secrets; NixOS activation decrypts with the machine key. User-key rotation re-encrypts one machine key per machine, not every secret. Shared secrets use age multi-recipient encryption for all machines’ public keys.

## Quick Start

### 1. Age identity

Private-key lookup, in order:

1. `AGE_KEY` environment variable (key content)
2. `AGE_KEYFILE` environment variable (key-file path)
3. `~/.config/age/identities`
4. `~/.config/sops/age/keys.txt`
5. `~/.age/key.txt`

Create an identity if needed:

```bash
mkdir -p ~/.config/age
age-keygen -o ~/.config/age/identities
```

Use the generated public key below. Hardware-token age-plugin identity files may be placed at any listed path.

### 2. Configure in `clan.nix`

```nix
{
  # Select the age backend
  vars.settings.secretStore = "age";

  # Your public key(s) as default recipients for all machines
  vars.settings.recipients.default = [
    "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"
  ];

  # Optionally override recipients for specific machines
  # vars.settings.recipients.hosts.my-machine = [
  #   "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"
  #   "age1another..."
  # ];
}
```

### 3. Generate

```bash
clan vars generate my-machine
```

`clan vars generate my-machine` auto-generates a missing machine keypair, encrypts its private key to recipient key(s), runs generators, encrypts generator outputs to the machine public key, and commits the results.

### 4. Deploy

```bash
clan machines update my-machine
```

Encrypted secrets are uploaded to the target; NixOS activation decrypts them on boot.

## Decryption Phases

Each secret file’s `neededFor` option controls activation timing:

|Phase|Decrypted to|When|Use case|
|---|---|---|---|
|`users`|`/run/user-secrets/` (tmpfs)|Before user/group creation|Secrets needed by user definitions (e.g., `hashedPasswordFile`)|
|`services`|`/run/secrets/` (tmpfs)|After users exist|Service credentials, API keys|
|`activation`|In-place at upload location|During activation|Secrets for other activation scripts|
|`partitioning`|`/run/partitioning-secrets/` (tmpfs)|During partitioning|Disk encryption keys|

Tmpfs secrets never touch disk and disappear on reboot; they are re-decrypted on the next boot.

## Configuration

`vars.settings.secretStore = "age"` selects this backend.

`vars.settings.recipients.hosts.<machine>` lists age public keys that decrypt the machine private key, typically admin keys:

```nix
vars.settings.recipients.hosts.webserver = [
  "age1admin1..."
  "age1admin2..."  # Multiple admins
];
```

`vars.settings.recipients.default` supplies fallback recipients when `recipients.hosts.<machine>` is not set; defaults do not combine with host-specific recipients:

```nix
vars.settings.recipients.default = [
  "age1admin..."
];
```

`clan.core.vars.age.secretLocation` sets the target upload location; default `/etc/secret-vars`:

```nix
clan.core.vars.age.secretLocation = "/etc/my-secrets";
```

## Repository Layout

```text
your-clan/
├── clan.nix
├── secrets/
│   ├── age-keys/
│   │   └── machines/
│   │       └── my-machine/
│   │           ├── pub          # Machine public key (plaintext)
│   │           └── key.age      # Machine private key (encrypted to user keys)
│   └── clan-vars/
│       ├── per-machine/
│       │   └── my-machine/
│       │       └── openssh/
│       │           └── ssh.id_ed25519.age
│       └── shared/
│           └── cluster-token/
│               └── token.age
└── vars/
    └── per-machine/
        └── my-machine/
            └── openssh/
                └── ssh.id_ed25519.pub/
                    └── value     # Public (non-secret) values
```

## Multiple Recipients

All listed recipients can decrypt a machine private key and run `clan vars generate` and `clan machines update` for that machine:

```nix
{
  vars.settings.recipients.hosts.production = [
    "age1admin1..." # Primary admin
    "age1admin2..." # Backup admin
    "age1cikey..." # CI/CD system
  ];
}
```

## Key Rotation and Machine Changes

After updating recipients in `clan.nix`, rotate admin access with:

```bash
# Update recipients in clan.nix, then:
clan vars fix my-machine
```

`clan vars fix my-machine` decrypts each machine key with the old identity and re-encrypts it to new recipients; secrets do not need re-encryption. Adding or removing machines causes shared secrets to be re-encrypted during `clan vars generate` to include or exclude the machine’s public key.

## Health Check

```bash
clan vars check my-machine
```

Checks that machine recipients are configured and an age identity is available for decryption.

## Troubleshooting

### "No age recipients configured for machine"

```nix
vars.settings.recipients.hosts.my-machine = [ "age1..." ];
```

### "No age identity found"

Use a well-known identity path or an environment variable:

```bash
# File-based
export AGE_KEYFILE=~/.config/age/identities

# Or inline
export AGE_KEY="AGE-SECRET-KEY-1..."
```

### "AGE_KEYFILE points to non-existent file"

Verify that the `AGE_KEYFILE` path exists and is readable.

## Comparison with SOPS Backend

|Feature|Age Backend|SOPS Backend|
|---|---|---|
|Encryption tool|age directly|sops (wrapping age)|
|Decryption location|Target machine (activation scripts)|Target machine (sops-nix)|
|Decryption binary|`age` (shell scripts)|`sops-install-secrets` (Go)|
|Machine keys|Auto-generated, in-repo|Auto-generated, in-repo|
|Key indirection|Yes (user → machine key → secret)|Yes (similar)|
|Shared secrets|Multi-recipient age encryption|sops-nix groups|
|Hardware tokens|Via age plugins|Via sops/age plugins|

## See Also

- [Age encryption tool](https://github.com/FiloSottile/age)
- [Introduction to Vars](../intro-to-vars)
- [SOPS Backend](../sops/secrets)
