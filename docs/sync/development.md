# Develop the sync application

The sync application is an isolated Bun and TypeScript project under `sync/`. See [Repository layout](../repository-layout.md) for the module map. For the shared-skill workflow, see [Manage shared skills](../skills.md).

## Run sync from source

From the repository root, use the public entrypoint:

```bash
bun ./sync/src/cli.ts
```

Keep `sync/src/cli.ts` as the public entrypoint. Do not add a `bin/` shell trampoline.

## Run the full checks

Run the static checks and the test suite from `sync/`:

```bash
cd sync
bun run check
bun run typecheck
bun test
bun run test:integration
```

`bun test` already includes `test/integration.test.ts`. Run the explicit integration command when you are iterating on process-level behavior.

## Run a focused test

Pass the test file to Bun:

```bash
cd sync
bun test ./test/managed-tools.test.ts
bun test ./test/wrappers.test.ts
```

Add the narrowest regression test that covers the changed sync contract.

Add process-level integration coverage when a change creates a generated target or crosses a runtime boundary. Use harness names and paths as fixtures or adapter boundaries.

Keep tests of harness implementations and harness-local behavior beside their source under `harnesses/`.

## Write useful tests

- Test one behavior at the lowest layer that observes it. Do not repeat the same scenario in unit and process-level suites.
- Test shared code once, beside the shared module. Do not copy identical tests into every consumer; a consumer test covers only its own wiring.
- Assert observable behavior and contracts, not fixtures, mocks, or implementation details.
- Add a test only when it can fail on a real regression. Delete tests that duplicate coverage or re-prove what another test already covers.
- Keep skill and harness tests beside their owning source. `sync/test/` covers sync behavior only.

## Change sync behavior

1. Find the owning module under `sync/src/`.
2. Add or update the focused test.
3. Make the smallest implementation change.
4. Run the focused test.
5. Run `bun run check`, `bun run typecheck`, and `bun test`.
6. Run `git diff --check` from the repository root.
7. Update the related page under `docs/sync/` when the change affects commands, paths, lifecycle, platforms, or generated behavior.

Keep these contracts intact:

- Keep `sync/src/cli.ts` as the public entrypoint.
- Keep wrapper generation inside the sync application.
- Validate external files and network data at their boundary.
- Keep filesystem operations safe to retry.
- Preserve unmanaged files unless recorded ownership permits cleanup.

## Change harness configuration

1. Edit the matching source under `harnesses/`.
2. Run `bun ./sync/src/cli.ts` from the repository root.
3. Inspect the generated root derived from the adapter's `homeSegments` and `runtimeSubdir` fields.
4. Run the wrapper with `--version`.

Keep harness-specific tests and documentation beside the owning source under `harnesses/`. Do not place them in `sync/test/` or `docs/`.

Do not edit a generated harness home. Sync replaces managed files on the next run.

## Add a harness adapter

1. Add the adapter to `sync/src/core/harness-adapters.ts`.
2. Add its source directory under `harnesses/<harness>/`.
3. Add wrapper tests for every supported platform.
4. Add integration coverage for generated files and hooks.
5. Run the full checks.
6. Update the [Harness adapter reference](harnesses.md) only when the adapter changes the shared workflow or requires a harness-specific user action.

Store launcher metadata in the adapter. Do not repeat package names, target homes, or hook rules in user configuration.

Do not add a supported-harness roster to the documentation. `HARNESS_ADAPTERS` owns that list.

## Build the package

Build the bundled distribution executable from `sync/`:

```bash
cd sync
bun run build
```
This bundles `sync/src/cli.ts` into `sync/dist/cli.js` and `sync/src/runtime/model-catalog-client.ts` into `sync/dist/runtime/model-catalog-client.js`. Local development commands continue to run from source via `bun ./sync/src/cli.ts`. Published wrappers resolve `@anntnzrb/agentium` from npm.

## Runtime boundary

Generated wrappers and normal harness invocations use the published package, not `sync/src/cli.ts` or a local development bundle. The published sync engine reads the current harness and configuration files from the host's `~/.config/agents/` tree, so those files can change without rebuilding the package.

The sync engine requires Bun only. It uses Bun's HTTP, package-manager, filesystem, and archive APIs instead of invoking `npm`, `git`, `gh`, `tar`, or `uv`. A harness package or configured hook can have separate runtime requirements.

## Package release and publication

The `@anntnzrb/agentium` package is published automatically to npm via the GitHub Actions workflow at `.github/workflows/publish-package.yml`.

### Publication workflow

Publication triggers on successful pushes to `main` affecting `sync/**` or `.github/workflows/publish-package.yml`. The workflow serializes release runs without cancelling an active build or publish operation, so a newer push waits for the current release to finish.

### Required repository secret

The workflow requires an npm token stored in repository secrets:

- Secret name: `NPM_TOKEN`
- Access: Automation or granular access token with write/publish permissions for the `@anntnzrb` npm scope.

The build job has only `contents: read` and receives no npm credentials. The publish job alone receives `NPM_TOKEN` and GitHub OIDC (`id-token: write`) to attach npm trusted provenance.

### Version and dist-tag policy

- **Version scheme**: CI generates a non-committed release version formatted as `0.1.<GITHUB_RUN_NUMBER>`. The checked-in repository manifest maintains the baseline version.
- **`latest` tag**: A publish promotes the newly built version to `latest`; a stale rerun skips promotion when `latest` is already at or ahead of its version.
- **`previous` tag**: Before publishing, the existing `latest` version is re-tagged as `previous`; initial releases with no prior `latest` version skip this step.
- **Reruns**: If the computed version was already published, or `latest` is already at or ahead of it, the workflow exits without changing dist-tags.
