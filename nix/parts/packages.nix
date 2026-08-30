{ inputs, ... }:
{
  perSystem =
    { craneLib, ... }:
    let
      src = craneLib.cleanCargoSource (inputs.self + "/sync");
      commonArgs = {
        inherit src;
        strictDeps = true;
      };
      cargoArtifacts = craneLib.buildDepsOnly commonArgs;
    in
    {
      packages.default = craneLib.buildPackage (
        commonArgs
        // {
          inherit cargoArtifacts;
          pname = "agentium";
          cargoExtraArgs = "--package app";
        }
      );
    };
}
