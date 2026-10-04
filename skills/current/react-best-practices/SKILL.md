---
name: react-best-practices
description: "Use when building or optimizing React or Next.js rendering, data fetching, bundles, or Server Actions, not styling."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Vercel React Best Practices

React/Next.js performance-optimization guidance from Vercel Engineering. Apply the smallest relevant rule set; do not apply every rule opportunistically.

## Apply when

- Writing new React components or Next.js pages
- Implementing client- or server-side data fetching
- Reviewing performance issues
- Refactoring existing React/Next.js code
- Optimizing bundle size or load times

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Pick a rule category by impact | `rules/_sections.md` | Before selecting optimization rules |
| Apply a specific optimization | Matching `rules/<rule-id>.md` | After identifying the bottleneck |
| Expanded Vercel guidance | `references/vercel-guide.md` | A broad review, or rule detail is insufficient |
| Secure Next.js Server Actions | `rules/server-auth-actions.md` | Creating or reviewing Server Actions |
| Human-facing package context | `README.md` | When needed |

## Category prefixes

1. Eliminating Waterfalls: `async-`
2. Bundle Size Optimization: `bundle-`
3. Server-Side Performance: `server-`
4. Client-Side Data Fetching: `client-`
5. Re-render Optimization: `rerender-`
6. Rendering Performance: `rendering-`
7. JavaScript Performance: `js-`
8. Advanced Patterns: `advanced-`

## Use

1. Start from the user-visible outcome or observed bottleneck.
2. Load `rules/_sections.md` to choose the relevant category.
3. Load only the matching rule files needed for the change.
4. Use `references/vercel-guide.md` only when a rule file is insufficient or a broad review requires the full compiled guide.
