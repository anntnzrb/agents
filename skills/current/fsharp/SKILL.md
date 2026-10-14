---
name: fsharp
description: "Use when writing F# code, editing .fs/.fsi/.fsx/.fsproj files, running dotnet fsi, or working on F# tests."
license: AGPL-3.0-or-later
---

# F# development

## Activation triggers

- F# implementation, project configuration, scripts, or tests.
- `.fs`, `.fsi`, `.fsx`, `.fsproj`, or `dotnet fsi` work.
- F# package, compiler, formatter, or test-runner compatibility.

## DETECT

Before editing, inspect the configuration that applies to the affected project:

- `global.json`: SDK selection and `test.runner`.
- `Directory.Build.props`, `Directory.Build.targets`, and project imports.
- `Directory.Packages.props` for Central Package Management (CPM), or Paket files.
- Effective `LangVersion`, `Nullable`, and `TreatWarningsAsErrors`.
- Resolved `FSharp.Core`, including SDK defaults and package overrides.
- `dotnet-tools.json` manifests and repository build, test, and format commands.
- A Nix dev shell, if present. Use it before installing tools.

## Edit within the detected setup

- Repository conventions and configured tools win over the defaults below.
- Never upgrade the SDK, `LangVersion`, or `FSharp.Core` to make code compile or use a newer feature.
- Add new source files to the `.fsproj` in dependency order, with each `.fsi` before its `.fs`.
- When adding or upgrading packages, including CPM `PackageVersion` pins, resolve "latest stable" only through listing-aware sources: `dotnet package search <id> --exact-match`, `dotnet list package --outdated`, or the registration API's `listed` flag. See `references/ecosystem.md` for metadata lookup.
- Never select versions from the NuGet flat-container index. Check each chosen version's dependency ranges for compatibility before building.
- If a test runner, adapter, or build breaks after a change, fix the version or configuration root cause. Never replace or override SDK targets such as `VSTest`, remove the adapter, or hand-roll a runner to make `dotnet test` pass.

## VERIFY

1. Run the repository gate for the change. If none exists, build the affected project.
2. Fix the earliest diagnostic in compile order before chasing downstream inference errors.
3. Run focused tests. Record executed test names or counts and the exit code. Exit zero with zero executed tests is not verification.
4. Run the repository-pinned formatter, using `dotnet tool run fantomas` or `dotnet fantomas --check` as configured.
5. Run analyzers only when the repository configures them.
6. Before handoff, run `git status --short`. Confirm every changed or untracked file is part of the requested change. Move or delete probes, scratch scripts, and test rigs you created unless the user asked to keep them.

Use `dotnet fsi --exec <probe.fsx>` for a one-shot probe. Replace the placeholder with the probe path and order `#load` directives as the project compiles files. An FSI pass does not validate the project.

Report the checks that actually ran. Name any check that could not run and its blocker.

## Greenfield defaults

Use these only when creating a project without an inherited setup:

- Target `net10.0`, enable `Nullable`, and set `TreatWarningsAsErrors` to `true`.
- Use CPM for package versions and Fantomas as a local tool.
- Use Expecto with Microsoft.Testing.Platform (MTP). Read the proven configuration in `references/ecosystem.md` before creating the test project.
- Add `Expecto.FsCheck` and FsCheck only for property tests.
- Add `FsToolkit.ErrorHandling` only when result composition justifies a dependency.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Detect effective settings, triage diagnostics, or verify a probe | [references/workflow.md](references/workflow.md) | The repository gate or project configuration is unclear |
| Resolve packages, gate newer features, or configure tests | [references/ecosystem.md](references/ecosystem.md) | Adding a dependency, updating package versions, using F# 9 or 10 features, or changing a runner |
