# Lies of P evaluation coverage

The corpus contains exactly 96 sequential, unique, stateless scenarios. Each has 3–5 expectations and one exact CLI invocation.

| Allocation | Cases | Scope |
|---|---:|---|
| Build, mechanics, matchup | 11 | Builds, combat mechanics, and named base matchups |
| Base chapters | 11 | One spoiler-gated route for every chapter |
| Exact base trophies | 43 | One coherent scenario for every exact base title in platinum.json |
| Exact Overture DLC trophies | 11 | One coherent scenario for every exact DLC title in platinum.json |
| Overture bosses | 8 | One coherent matchup per named DLC boss |
| Spoiler/JSON/error/source/version/licensing | 9 | Policy and observable CLI errors |
| Farms and troubleshooting | 3 | Deterministic loops and diagnostic signals |

Every case names one scenario in both prompt and expected output, uses only the command family appropriate to that scenario, and separates deterministic facts from advisory guidance. Expectations enforce the 1.12.0.0 data scope, Legendary Stalker default, explicit `--spoilers` and `--dlc` gates, stateless save/inventory assumptions, provenance, confidence, and licensing/terms where sources are involved. Unsupported fields and invalid commands must produce explicit errors or uncertainty rather than invented claims. JSON cases require `--json`; source cases preserve URL, title, kind, checked version, scope, confidence, and terms.
