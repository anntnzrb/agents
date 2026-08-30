{ inputs, ... }:
{
  imports = [ inputs.git-hooks.flakeModule ];

  perSystem =
    { rustToolchain, ... }:
    {
      pre-commit = {
        check.enable = false;
        settings = {
          hooks = {
            clippy = {
              enable = true;
              packageOverrides.cargo = rustToolchain;
              packageOverrides.clippy = rustToolchain;
              settings.extraArgs = "--manifest-path sync/Cargo.toml";
            };
            rustfmt = {
              enable = true;
              packageOverrides.rustfmt = rustToolchain;
              settings.manifest-path = "sync/Cargo.toml";
            };
          };
        };
      };
    };
}
