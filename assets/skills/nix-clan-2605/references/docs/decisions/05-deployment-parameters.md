# 05 Deployment Parameters

Status: accepted

## Context

- `install`: always evaluates locally, then pushes the derivation to a remote system.
- `update`: configurable `buildHost` and `targetHost`, but always evaluates on `targetHost`.

Install/update therefore have different host semantics.

## Decision

`install` and `update` expose three hosts:

- `evalHost`: machine evaluating the NixOS configuration. If not `localhost`, upload non-secret vars and the Nix archived flake (usually one operation) to `evalMachine`.
- `buildHost`: machine building; corresponds to `--build-host` for `nixos-rebuild` or `--builders` for `nix build`.
- `targetHost`: machine receiving and activating the closure, through `install` or `switch-to-configuration`; corresponds to `--targetHost` for `nixos-rebuild` or the usual `nixos-anywhere` destination.

Hosts come from CLI args (or GUI forms) or inventory. CLI args take precedence when both specify a host.

## Consequences

- Simple flags support every deployment model of every tool; semantics are clearer and documentation is easier.
- Rework install: `nixos-anywhere` has problems when `evalHost` and `targetHost` are the same machine. Kexec first, then use the kexec image (or installer) as `evalHost`.
- If `evalHost` cannot access `targetHost` or `buildHost`, set up temporary entries for the command lifetime.
