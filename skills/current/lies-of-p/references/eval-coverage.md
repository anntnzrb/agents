# Lies of P evaluation coverage

The corpus contains exactly 96 sequential, unique, stateless scenarios. Each has 3–5 expectations and one exact CLI invocation.

| Allocation | Cases | Scope |
|---|---:|---|
| Build, mechanics, and weaknesses | 11 | Builds, combat mechanics, and enemy-class matchups |
| Routes and checklists | 11 | One spoiler-gated route for every base chapter |
| Exact base and Overture trophies | 54 | Every title in `platinum.json` |
| Named base and Overture bosses | 8 | Focused, spoiler-gated matchup scenarios |
| Community and displayed-AR comparator | 8 | Consensus/dissent, crit distinction, refusal, ranking, crit math, and malformed input |
| Source provenance | 2 | Status, version, licensing, and access limits |
| Audit error contract | 1 | Observable argparse failure |
| Farming | 1 | Deterministic loop with yield uncertainty |

Every case names one scenario in both prompt and expected output, uses only the command family appropriate to that scenario, and separates deterministic facts from advisory guidance. Community cases use `community` and comparator cases use `compare`; they never mix command families. Expectations enforce the 1.12.0.0 + Overture scope, Legendary Stalker default, explicit `--spoilers` and `--dlc` gates, stateless save/inventory assumptions, provenance, confidence, and licensing/terms where sources are involved. Community preferences are sentiment rather than mechanics. Comparator cases preserve displayed AR separately and document excluded enemy defense, hidden scaling/saturation, animation DPS, status buildup, and Fable effects. Unsupported fields and invalid commands must produce explicit errors or uncertainty rather than invented claims. JSON cases require `--json`; source cases preserve URL, title, kind, checked version, scope, confidence, and terms.
