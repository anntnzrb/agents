# Context7 Library Resolution

Guidelines for selecting, ranking, and disambiguating Context7 library IDs.

## Table of Contents

- [Library ID structure](#library-id-structure)
- [Name normalization](#name-normalization)
- [Evaluation metrics](#evaluation-metrics)
- [Disambiguation rules](#disambiguation-rules)
- [Version selection](#version-selection)
- [Operational limits and guardrails](#operational-limits-and-guardrails)

---

## Library ID structure

Context7 library identifiers use standard hierarchical paths:

- Canonical repository: `/org/project` (e.g. `/facebook/react`, `/vercel/next.js`, `/effect-ts/effect`)
- Documentation website: `/websites/project_dev` (e.g. `/websites/react_dev_reference`)
- Version-specific index: `/org/project/version` (e.g. `/vercel/next.js/v14.3.0`, `/facebook/react/v18.2.0`)

All queries to `docs` MUST begin with a leading forward slash `/`.

---

## Name normalization

When calling `library`, prefer the official library name with proper capitalization and punctuation:

| Official Name (Preferred) | Avoid |
|---|---|
| `"Next.js"` | `"nextjs"` |
| `"Three.js"` | `"threejs"` |
| `"Customer.io"` | `"customerio"` |
| `"Tailwind CSS"` | `"tailwindcss"` |
| `"Express"` | `"expressjs"` |

---

## Evaluation metrics

When `library` returns multiple candidate results, evaluate the following fields:

| Field | Range | Guidance |
|---|---|---|
| `trustScore` | 0 to 10 | Prefer candidates with score 8 or higher from official organizations. |
| `benchmarkScore` | 0 to 100 | Indicates index quality and documentation completeness. Prefer higher scores. |
| `totalSnippets` | Integer | Higher snippet counts provide broader API coverage and realistic examples. |
| `lastUpdateDate` | ISO 8601 | Prefer recently updated documentation when APIs evolve rapidly. |

---

## Disambiguation rules

1. Add a context query when searching common names:
   - `bun x ctx7@latest library "Effect" "Schema.Struct and Schema.TaggedError"` resolves `@effect/schema` vs legacy packages.
   - `bun x ctx7@latest library "Next.js" "app router Server Actions"` resolves Next.js App Router vs Pages Router.

2. Distinguish monorepo sub-packages:
   - Search with the exact package name first (e.g. `@effect/platform`, `@tanstack/react-query`).
   - If no exact package match is returned, search the parent repository identifier.

3. Reject unknown low-trust candidates:
   - If multiple candidates have similar names, choose the one matching the verified GitHub organization or official website domain.

---

## Version selection

- Major version migrations: When migrating between breaking versions (such as React 18 to 19, or Next.js 13 to 15), check the `versions` list returned by `library`.
- Specify the exact version ID when troubleshooting legacy codebases:
  ```bash
  bun x ctx7@latest docs /facebook/react/v18.2.0 "useTransition hook"
  ```
- Use the canonical unversioned ID for modern standard library usage.

---

## Operational limits and guardrails

1. Cap calls to at most 3 `library` and 3 `docs` invocations per question to prevent search loops.
2. If unresolved after 3 attempts, proceed with the best available data.
3. Keep queries focused on single concepts to avoid diluted rankings.
4. Never include credentials, API keys, or private code in search queries.
5. Always cite the resolved library ID in your final answer.
