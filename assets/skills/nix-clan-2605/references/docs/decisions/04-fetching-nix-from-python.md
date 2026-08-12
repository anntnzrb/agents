# 04 Fetching Nix From Python

## Status

accepted

## Context

`clan-cli` needs many Nix values in Python: hostnames, target IP addresses, variable-generation scripts, file locations, and more. Existing approaches:

### Method 1: `deployment.json`

Build-time JSON artifact serializing predefined values.

Downsides:

- No flake-level values.
- All-or-nothing caching: values are either cached there or not, so only cheap values fit; previously adding variable-generation scripts caused huge build-time overhead for every action.
- Duplicated Nix: values are defined at their module-system location (`clan.core.vars.generators`) and accumulated again for `deployment.json` (`system.clan.deployment.data`), adding unnecessary NixOS module-system dependencies.

Benefit: simple `nix build` caching.

### Method 2: direct access

Python directly invokes the evaluator/build sandbox through `nix build` and `nix eval`.

Downsides:

- No access caching: each Nix command incurs ~1.5s static overhead. The overhead varies with the requested value because `evalModules` cost differs between machine attributes and flake attributes; retrieving more attributes increases overhead and causes a linear performance decrease.
- CLI-interaction and error-handling boilerplate repeats per attribute.

Benefits: native Nix-command interaction is simple and intuitive; per-attribute error handling is easy.

Custom Nix expressions can provide values excluded from `deployment.json` or fetch flake-level values, but add:

- Technical debt: embedded expressions in Python are error-prone, unsupported by language linters, commonly erroneous, and harder to debug; missing-value and reported-build-error paths require custom error reporting.
- No caching/sharing infrastructure: values must be stored through one of the existing classes or not cached. Even cached expressions cannot share results: e.g. separate expressions fetching (1) paths and values for all generators and (2) values only must both execute in both contexts, although (2) could be skipped when (1) is cached.

### Method 3: `nix select`

Move all Nix-value extraction into a common class.

Downside: maintaining a custom DSL adds complexity.

Benefits:

- Select DSL API retrieves Nix values without complex custom expressions.
- Values can be cached beyond one CLI runtime.
- Endpoints can precache values, eliminating most repeated Nix evaluations except when the cache breaks or an expensive value's need is unknown until later.

## Decision

Use Method 3 (`nix select`) to extract Nix values. Add `Flake` in `flake.py`; its `select` method accepts a selector string and returns a Python dict.

Example:

```python
from clan_lib.flake import Flake
flake = Flake("github:lassulus/superconfig")
flake.select("nixosConfigurations.*.config.networking.hostName)
```

returns:

```json
{
  "ignavia": "ignavia",
  "mors": "mors",
  ...
}
```

## Consequences

- Faster execution: caching usually extends beyond one execution; without a cache break, execution is essentially instant because Nix need not run again.
- Better error reporting: one chokepoint handles all Nix values, parses errors, and presents friendlier messages, e.g. when a value is missing at its expected module-system location.
- Less embedded Nix in Python.
- More portable CLI: fewer modules need importing into the module system; Python can extract most values directly.
