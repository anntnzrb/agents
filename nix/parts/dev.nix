{
  perSystem =
    {
      pkgs,
      config,
      rustToolchain,
      ...
    }:
    {
      devShells.default = pkgs.mkShell {
        name = "agentium-dev";
        packages = [
          rustToolchain
          pkgs.bun
          pkgs.cargo-nextest
          pkgs.cargo-generate
          pkgs.watchexec
        ];

        shellHook = ''
          ${config.pre-commit.installationScript}
          echo "🦀 Rust $(rustc --version) Agentium development environment loaded!"
        '';
      };
    };
}
