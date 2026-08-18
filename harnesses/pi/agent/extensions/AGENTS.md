# Pi extension engineering policy

## Scope and routing

This policy applies to active Pi extensions under this directory. Pi loads each extension as a hosted TypeScript module.

Load the TypeScript skill for implementation, tests, compiler config, ESM, packages, and Bun tooling. Also load the Effect skill for Effect code. Those skills own the general stack. This file owns Pi-specific constraints. Pi's hosted boundary overrides standalone-application instructions.

## Respect the Pi host

- Export the factory required by the installed `ExtensionAPI`.
- Do not add `main`, call `BunRuntime.runMain`, or install process and signal lifecycle handlers.
- Do not use `Bun.*` globals. Pi does not guarantee a Bun host.
- Use portable APIs where practical. Use `node:` modules only when Pi requires them and Bun supports them.
- Start resources from `session_start` or from the callback that needs them. Close them idempotently in `session_shutdown`.
- Do not start background resources from the extension factory. Pi may load it without starting a session.
- Pass Pi abort signals to cancellable work.
- Use `pi.exec` or asynchronous process APIs. Never block Pi with synchronous subprocesses, synchronous filesystem work, or busy loops.

For Effect code, do not add `@effect/platform-bun`. Execute one final Effect at the Pi factory, command, tool, or event boundary, never inside business logic.

Pi marks a tool failure only when `execute` throws. Keep failures typed internally, then translate and throw once at the boundary. Returning `isError` does not fail a tool.

Get approval before adding a standalone companion process.

## Follow current Pi contracts

Before coding, read the installed Pi `README.md` and `docs/extensions.md` completely. Follow relevant links and inspect the nearest example under `examples/extensions/`. Read `docs/tui.md` completely before using TUI APIs. Installed exports and declarations override old tutorials and memory.

For custom tools:

- Use Pi's TypeBox contract for `registerTool` parameters. Effect `Schema` may own domain and external-data boundaries, not Pi's tool schema.
- Pass cancellation signals to blocking work and throw to report failure.
- Truncate output at Pi's current limits and identify where complete output is stored.
- Wrap the full read-modify-write window in `withFileMutationQueue`. Resolve the real target path first.
- Preserve the exact result shape when overriding a built-in tool.
- Name the tool in each `promptGuidelines` entry.

Use `ctx.isProjectTrusted()` before reading project-local config. Persist branch-sensitive state in tool-result details or Pi session entries so reload, resume, fork, and tree navigation reconstruct it.

Do not add custom rendering, editors, overlays, widgets, footers, or other TUI behavior unless requested. Guard terminal-only APIs with `ctx.mode === "tui"` and dialog APIs with `ctx.hasUI`.

## Package and validate

For distributable packages, put Pi-provided packages in `peerDependencies`, runtime imports in `dependencies`, and development tools in `devDependencies`. Keep the `pi` manifest limited to exported resources.

Use `bun:test`. Test observable behavior at the lowest useful layer, including Pi callbacks, state reconstruction, cancellation, cleanup, truncation, and file mutation when relevant.

For runtime-facing changes, validate a fresh extension when credentials and cost permit:

```text
pi --no-extensions -e <extension.ts> --no-session --mode json -p --tools <tools> "<scenario>"
```

Use JSONL events and filesystem effects as evidence. Import success, `--help`, and type checks do not prove runtime behavior.

Update the extension README when public commands, tools, configuration, or behavior change. Run the owning skills' gates and `git diff --check`. Report whether Pi needs `/reload` or restart.
