# Migrate `admin` to `sshd` + `users`

`admin` clanService deprecated; functionality split:
- `sshd` server role: SSH authorized keys, host certificates, RSA host-key generation
- `users`: root-password management

## Mappings

|Deprecated|Replacement|
|---|---|
|`allowedKeys`|`sshd` server `authorizedKeys`|
|`certificateSearchDomains`|`sshd` server `certificate.searchDomains`|
|`rsaHostKey.enable`|`sshd` server `hostKeys.rsa.enable`|
|root password|`users` `user = "root"`|

## Migration

`admin` configuration:

```nix
instances = {
  admin = {
    roles.default.tags = [ "all" ];
    roles.default.settings = {
      allowedKeys = {
        "my-key" = "ssh-ed25519 AAAA...";
      };
      certificateSearchDomains = [ "mydomain.com" ];
      rsaHostKey.enable = true;
    };
  };
};
```

Replace it with `sshd` and its `server` role:

```nix
instances = {
  sshd = {
    roles.server.tags = [ "all" ];
    roles.server.settings = {
      authorizedKeys = {
        "my-key" = "ssh-ed25519 AAAA...";
      };
      certificate.searchDomains = [ "mydomain.com" ];
      hostKeys.rsa.enable = true;
    };
    # Optional: add client role if you want machines to trust the CA
    roles.client.tags = [ "all" ];
  };
};
```

If relying on `admin` root-password generation, add `users` (set `prompt = false` to auto-generate rather than prompt):

```nix
instances = {
  root-user = {
    module = {
      name = "users";
      input = "clan-core";
    };
    roles.default.tags = [ "all" ];
    roles.default.settings = {
      user = "root";
      prompt = true;  # Set to false to auto-generate password
    };
  };
};
```

## Vars migration

After updating configuration, regenerate vars with:

```sh
clan vars generate $MACHINE_NAME
```

|Old var path|New service var path|
|---|---|
|`root-password/password-hash`|`user-password-root/user-password-hash`|
|`admin-ssh-rsa/*`|`openssh-rsa/*`|
|`admin-ssh/*`|`openssh/*`|

## Inventory example

Before:

```nix
{
  flake.clan.inventory.instances = {
    admin = {
      roles.default.machines.my-server = { };
      roles.default.settings = {
        allowedKeys = {
          "admin-key" = "ssh-ed25519 AAAA...xyz admin@workstation";
        };
        certificateSearchDomains = [ "internal.example.com" ];
      };
    };
  };
}
```

After:

```nix
{
  flake.clan.inventory.instances = {
    sshd = {
      roles.server.machines.my-server = { };
      roles.server.settings = {
        authorizedKeys = {
          "admin-key" = "ssh-ed25519 AAAA...xyz admin@workstation";
        };
        certificate.searchDomains = [ "internal.example.com" ];
      };
      roles.client.machines.my-server = { };
    };

    root-password = {
      module = {
        name = "users";
        input = "clan-core";
      };
      roles.default.machines.my-server = { };
      roles.default.settings = {
        user = "root";
        prompt = true;
      };
    };
  };
}
```

`sshd` also provides a `client` role for SSH-CA trust and TOFU-less verification. See [sshd service documentation](https://clan.lol/docs/26.05/services/official/sshd).
