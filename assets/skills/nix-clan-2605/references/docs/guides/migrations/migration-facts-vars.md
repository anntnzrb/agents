# Migration Facts Vars

## `facts` → `vars`

Guide for migrating modules from the `facts` backend to the `vars` backend. The [`vars` module](https://clan.lol/docs/26.05/reference/clan.core/vars) and Clan [`vars` command](https://clan.lol/docs/26.05/reference/cli/vars) work in tandem; keep them in sync.

:::admonition[Facts System Removed]{type=warning}

`facts` is fully removed from clan-core; automatic migration via `migrateFact` is unavailable. Manually migrate secrets and values:

1. Locate old facts in the storage backend (`sops`, `password-store`, or in-repo).
2. Copy their values.
3. Run `clan vars generate`, then override generated values with the old values using `clan vars set`.

Alternative: roll back to a clan-core version before December 2025 and use automatic migration.
:::

### Keep Existing Values (historical; removed feature)

Previously, a vars generator could preserve an existing fact with:

```nix
migrateFact = "fact-name"
```

During vars generation, an existing fact with that name was migrated to vars. Example: `facts.services.vaultwarden.secret.admin` means the `vaultwarden` fact service has an `admin` secret; its historical vars mapping was:

```nix
vars.generators.vaultwarden = {
    migrateFact = "vaultwarden";  # No longer functional
    files.admin = {};
};
```

This vars generator generates the `admin` file. The configuration is historical and `migrateFact` no longer works.

### Prompts

A prompt requests user input. `vars` provides a shorthand; the former facts pattern was:

```nix
facts.services.forgejo-api = {
    secret.token = {};
    generator.prompt = "Please insert your forgejo api token";
    generator.script = "cp $prompt_value > $secret/token";
};
```

Equivalent `vars` shorthand (also supports multiple prompts per generator):

```nix
vars.generators.forgejo-api = {
    prompts.token = {
        description = "Please insert your forgejo api token"
        persist = true;
    };
};
```

For more control, use a file plus prompt description and script:

```nix
vars.generators.forgejo-api = {
    files.token = {};
    prompts.token.description = "Please insert your forgejo api token";
    script = "cp $prompts/<name> $out/<name>";
};
```

### Complete module migration

Historical `facts` syncthing module:

```nix
facts.services.syncthing = {
  secret.key = {};
  secret.cert = {};
  public.id = {};

  generator.path = [
    pkgs.coreutils
    pkgs.gnugrep
    pkgs.syncthing
  ];

  generator.script = ''
    syncthing generate --config "$out"
    mv "$out"/key.pem "$secret"/key
    mv "$out"/cert.pem "$secret"/cert
    cat "$out"/config.xml | grep -oP '(?<=<device id=")[^"]+' | uniq > "$public"/id
  '';
};
```

Historical corresponding `vars` module:

```nix
vars.generators.syncthing = {
  migrateFact = "syncthing";

  files.key = {};
  files.cert = {};
  files.id.secret = false;

  runtimeInputs = [
    pkgs.coreutils
    pkgs.gnugrep
    pkgs.syncthing
  ];

  script = ''
    syncthing generate --config "$out"
    mv "$out"/key.pem "$out"/key
    mv "$out"/cert.pem "$out"/cert
    cat "$out"/config.xml | grep -oP '(?<=<device id=")[^"]+' | uniq > "$out"/id
  '';
};
```

`vars` keeps most usage patterns but uses one `files` attribute instead of separate `public`/`secret` definitions. Files are secret by default; mark public files with `secret = false`. In the example, `generator.path` becomes `runtimeInputs`, and generated files use `$out`.
