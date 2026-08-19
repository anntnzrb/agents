# Create an SSH Key

:::admonition[Tip]{type=tip}
Check for an existing key pair; create one if absent.
:::

Check for an existing pair:

```bash
ls ~/.ssh/id_ed25519*
```

Both `id_ed25519` and `id_ed25519.pub` listed → ready.

`No such file or directory` → create the pair:

```bash
ssh-keygen -t ed25519
```

Prompts:

- File location: press Enter for the default (`~/.ssh/id_ed25519`)
- Passphrase: enter one or press Enter for none

Created files:

- `~/.ssh/id_ed25519`: private key; keep secret
- `~/.ssh/id_ed25519.pub`: public key; share with target machines

Verify both files exist:

```bash
ls ~/.ssh/id_ed25519*
```

Both files should be listed.
