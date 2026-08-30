{ inputs, ... }:
{
  perSystem =
    { pkgs, system, ... }:
    let
      rustToolchain = inputs.fenix.packages.${system}.complete.toolchain;
      craneLib = (inputs.crane.mkLib pkgs).overrideToolchain rustToolchain;
    in
    {
      _module.args = {
        inherit rustToolchain craneLib;
      };
    };
}
