# Custom vars generator: hashed root password

Workflow: declare generator → inspect status → generate → review repository changes → update machine → regenerate password as needed.

API: https://clan.lol/docs/26.05/reference/clan.core/vars

## Declare

Create `root-password.nix` and import it from `configuration.nix`. This generator prompts for a hidden password, does not persist the prompt, runs `mkpasswd`, stores the hash, and exposes its path:

```nix
{ config, pkgs, ... }:
{

  clan.core.vars.generators.root-password = {
    # prompt the user for a password
    # (`password-input` being an arbitrary name)
    prompts.password-input.description = "the root user's password";
    prompts.password-input.type = "hidden";
    # don't store the prompted password itself
    prompts.password-input.persist = false;
    # define an output file for storing the hash
    files.password-hash.secret = false;
    # define the logic for generating the hash
    script = ''
      cat $prompts/password-input | mkpasswd > $out/password-hash
    '';
    # the tools required by the script
    runtimeInputs = [ pkgs.mkpasswd ];
  };

  # ensure users are immutable (otherwise the following config might be ignored)
  users.mutableUsers = false;
  # set the root password to the file containing the hash
  users.users.root.hashedPasswordFile =
    # clan will make sure, this path exists
    config.clan.core.vars.generators.root-password.files.password-hash.path;
}
```

## Inspect and generate

```console
$ clan vars list my-machine
root-password/password-hash: <not set>
```

`root-password/password-hash` is initially unset. Generation is optional: `clan machines update` also triggers it.

```console
$ clan vars generate my-machine
Enter the value for root-password/password-input (hidden):
```

After input:

```console
Updated var root-password/password-hash
  old: <not set>
  new: $6$RMats/YMeypFtcYX$DUi...
```

## Repository changes

Generation creates `vars/per-machine/my-machine/root-password/password-hash/value`. In a git repository, it also creates a commit:

```console
$ git log -n1
commit ... (HEAD -> main)
Author: ...
Date:   ...

    vars: update via generator root-password (machine: my-machine)
```

## Deploy

```shell
clan machines update my-machine
```

## Change the root password

Replace `my-machine` with the machine name, then regenerate:

```console
$ clan vars generate my-machine --generator root-password --regenerate
...
Enter the value for root-password/password-input (hidden):
Input received. Processing...
...
Updated var root-password/password-hash
  old: $6$tb27m6EOdff.X9TM$19N...

  new: $6$OyoQtDVzeemgh8EQ$zRK...
```
