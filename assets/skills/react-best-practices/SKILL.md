---
name: react-best-practices
description: Write, review, or optimize React and Next.js performance, data fetching, bundles, and Server Actions security.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Vercel React Best Practices

React and Next.js performance optimization guidance from Vercel Engineering. Use the smallest relevant rule set for the task; do not apply every rule opportunistically.

## When to Apply

Reference these guidelines when:

- Writing new React components or Next.js pages
- Implementing data fetching (client or server-side)
- Reviewing code for performance issues
- Refactoring existing React/Next.js code
- Optimizing bundle size or load times

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Pick a rule category by impact | `rules/_sections.md` | Before selecting optimization rules |
| Apply a specific optimization | Matching `rules/<rule-id>.md` | After identifying the bottleneck |
| Review expanded Vercel guidance | `references/vercel-guide.md` | Broad review or insufficient rule detail |
| Secure Next.js Server Actions | `rules/server-auth-actions.md` | Creating or reviewing Server Actions |
| Package overview for humans | `README.md` | Human-facing package context is needed |

## Category Prefixes

| Priority | Category                  | Prefix       |
| -------- | ------------------------- | ------------ |
| 1        | Eliminating Waterfalls    | `async-`     |
| 2        | Bundle Size Optimization  | `bundle-`    |
| 3        | Server-Side Performance   | `server-`    |
| 4        | Client-Side Data Fetching | `client-`    |
| 5        | Re-render Optimization    | `rerender-`  |
| 6        | Rendering Performance     | `rendering-` |
| 7        | JavaScript Performance    | `js-`        |
| 8        | Advanced Patterns         | `advanced-`  |

## Use

1. Start from the user-visible outcome or observed bottleneck.
2. Load `rules/_sections.md` to choose the relevant category.
3. Load only the matching rule files needed for the change.
4. Use `references/vercel-guide.md` only when a rule file is insufficient or a broad review requires the full compiled guide.
