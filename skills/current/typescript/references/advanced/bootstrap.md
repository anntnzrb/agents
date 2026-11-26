# Bootstrap: Runtime, Package Manager, Tooling

When starting a new TypeScript project (or scripting against the world), the choice of runtime, package manager, framework, and toolchain compounds. The wrong default at minute zero costs hours every week.

For a new user-owned backend, CLI, automation, infrastructure, service, or data-processing application, [`../bun-application.md`](../bun-application.md) is the controlling policy: Bun, native TypeScript 7+, Oxlint, Oxfmt, `bun:test`, and no validation or HTTP framework by default. This file is a recipe library for concrete requirements, approved alternates, and inherited stacks; it must not override that policy or an existing repository's toolchain.

## Runtime decision tree

```
Is this a CLI / script / single-binary tool?
└─ Yes → Bun (single executable, hot reload, native TS)
        Use `bun run script.ts` directly. No build step.

Is this a backend service?
├─ Edge (Cloudflare Workers / Vercel / Deno Deploy) → match the platform
├─ Bun-supported runtime          → Bun; add a framework only for a concrete need
├─ Need Node-only deps (sharp, native modules without Bun support) → approved Node runtime
└─ Otherwise                       → Bun; add a framework only for a concrete need

Is this a frontend?
└─ Vite (regardless of framework). Bun for the package manager.

Is this a library to publish to npm?
└─ tsdown (or unbuild). Targets Node 20+. Preserve the repository's package manager.
```

## Bun is the default runtime

Use Bun for:
- Scripts and CLIs (`bun run` is faster than `tsx` and `ts-node`)
- New backends (Hono runs natively, hot reload via `bun --hot`)
- Test runner (`bun test` is built-in, faster than vitest for small suites)
- Package manager (`bun install` is faster than `pnpm` and far faster than `npm`)

Use Node only for an inherited Node project or after explicit approval when:
- A dependency uses native modules Bun can't load (rare in 2026; check the dep's release notes)
- Production target is a Node-specific platform (some serverless platforms don't run Bun yet)
- You're contributing to a Node-only project

`bunx` replaces `npx`. `bun create` scaffolds projects.

## Package manager: Bun first, existing lockfiles win

Use Bun for a new user-owned application. If an approved alternate requires Node, preserve the repository's existing package manager. Choose pnpm only for a new approved Node project or when the user explicitly requests migration; do not create a second lockfile.

Why pnpm when Node and pnpm are already approved:
- Content-addressable store: 10x less disk usage on a machine with many projects
- Strict node_modules layout: phantom dependencies fail at install time, not at runtime
- Workspaces are first-class
- Significantly faster than npm

Why not yarn:
- Yarn classic is unmaintained
- Yarn berry's "PnP" mode breaks with editor tooling more often than it should
- pnpm has caught up on every yarn berry feature people actually use

Why not npm:
- Slowest of the three
- No proper workspace story until very recently
- Phantom dependencies allowed by default

When the user explicitly approves an npm/yarn → pnpm migration:

```bash
pnpm import   # reads package-lock.json or yarn.lock and produces pnpm-lock.yaml
rm -rf node_modules package-lock.json yarn.lock
pnpm install
```

## Backend framework: only for a concrete HTTP need

Do not add a framework merely because the service uses HTTP. Prefer Bun and Web platform primitives while they satisfy the requirement. When routing, middleware, or multi-runtime portability makes a framework necessary, Hono is a suitable opt-in recipe:

- Type-safe end-to-end (request/response types flow through middleware)
- Edge-compatible (runs on Bun, Node, Cloudflare Workers, Deno, AWS Lambda)
- Maintained, opinionated, and documented well

Pair Hono with `hono-openapi` + `@scalar/hono-api-reference` + `@hono/swagger-ui` only when the service must emit or host OpenAPI documentation. The Zod examples in [backend-hono.md](backend-hono.md) are an opt-in validation stack, not the greenfield default; follow `../bun-application.md` before adding Zod or another validation library.

Avoid for new services unless inherited or explicitly approved:
- Express: legacy API shape and middleware ecosystem
- Fastify: a viable inherited stack, but not the default recipe here
- NestJS: the Angular-flavoured DI/decorator stack is overkill for most services
- Bare `Bun.serve` or `node:http` once routing, middleware, or validation requirements make them a hand-rolled framework

## Frontend tooling: Vite

Vite for any frontend. Replaces webpack, parcel, rollup-as-app-bundler. Works with React, Vue, Svelte, Solid, Preact, vanilla.

```bash
bun create vite my-app -- --template react-ts
cd my-app
bun install
bun run dev
```

## Lint + format: Oxlint and Oxfmt by default

For a new user-owned Bun application, follow `../bun-application.md`:

```bash
bun add --dev oxlint oxfmt
bunx oxlint .
bunx oxfmt --check .
```

Biome remains a reasonable opt-in for repositories that already use it or explicitly choose one lint-and-format tool:

```bash
bun add --dev @biomejs/biome
bun biome init
```

Use ESLint only when an existing project or required plugin ecosystem owns it. Never run overlapping formatters; pick one formatting owner.

## Test runner: `bun test` by default

| Runner | Use when |
|---|---|
| `bun test` | New Bun applications and ordinary unit tests |
| `vitest` | Existing Vitest repositories, Vite-based frontend infrastructure, DOM/browser tests, or another concrete Vitest-only requirement |

NEVER Jest for a new project. Jest's CommonJS-first design fights every modern Node/TS project.

## TypeScript

`tsconfig.json` for a Bun + Hono backend:

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "Preserve",
    "moduleResolution": "bundler",
    "moduleDetection": "force",
    "allowImportingTsExtensions": true,
    "lib": ["ESNext"],
    "types": ["bun"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "exactOptionalPropertyTypes": true,
    "esModuleInterop": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "verbatimModuleSyntax": true,
    "noEmit": true
  },
  "include": ["src/**/*", "tests/**/*"]
}
```

`verbatimModuleSyntax: true` enforces explicit `import type { ... }` for type-only imports; pairs with the no-excuse rule on type-only imports.

`noEmit: true` because `bun run` and `bun build` handle compilation. The `tsc` command becomes a typechecker only.

## Quick-start: Bun + Hono backend when routing is a concrete need

```bash
mkdir my-api && cd my-api
bun init -y
bun add hono
bun add --dev typescript@latest @types/bun oxlint oxfmt
```

`package.json` scripts:

```json
{
  "scripts": {
    "dev": "bun run --hot src/index.ts",
    "start": "bun run src/index.ts",
    "build": "bun build src/index.ts --target bun --outdir dist",
    "typecheck": "bunx tsc --project tsconfig.json --noEmit",
    "lint": "oxlint .",
    "format": "oxfmt .",
    "format:check": "oxfmt --check .",
    "test": "bun test"
  }
}
```

Wire a minimal Hono `app.ts`. If the service must emit or host OpenAPI documentation, load [backend-hono.md](backend-hono.md) and consciously adopt its validation stack rather than adding Zod by default.

## When NOT to bootstrap from scratch

| Situation | Use |
|---|---|
| Internal tool with auth/admin/dashboards | Next.js (full-stack) - lots of free wiring |
| Documentation site | Astro or VitePress |
| Real-time features (WebRTC, complex sockets) | Bun plus a real-time library chosen for the protocol |
| Data-heavy SPA | Vite + React + TanStack Query + TanStack Router |

For greenfield backend services, start with Bun and the smallest HTTP surface that meets the requirement. Add Hono only when routing, middleware, or portability makes it a concrete need.
