{ inputs, ... }:
{
  imports = [ inputs.treefmt-nix.flakeModule ];

  perSystem =
    { lib, pkgs, ... }:
    {
      treefmt = {
        projectRoot = lib.cleanSource ../..;
        projectRootFile = "flake.nix";
        programs.nixfmt = {
          enable = true;
          package = pkgs.nixfmt;
        };
        programs.rustfmt = {
          enable = true;
          package = pkgs.rustfmt;
        };
      };
    };
}
