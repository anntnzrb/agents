# Detect and verify an F# change

Read when the project configuration or verification command is unclear.
Commands below use `App.fsproj`, `Tests.fsproj`, and `probe.fsx` as example names. Replace them with the actual paths. Run from the repository's intended working directory so SDK and tool-manifest discovery match CI.

## Detect the effective configuration

1. Read the repository instructions, CI, and task runner for the supported environment and gate.
2. If a Nix dev shell exists, enter it with `nix develop` before running .NET commands.
3. Inspect `global.json` in the working directory and its ancestors. Record the SDK policy and test runner.
4. Inspect the project and its imported props and targets. Include `Directory.Build.props`, `Directory.Build.targets`, `Directory.Packages.props`, and any Paket configuration.
5. Query evaluated settings rather than inferring them from one file:

```text
dotnet --version
dotnet --info
dotnet msbuild App.fsproj -getProperty:LangVersion -getProperty:Nullable -getProperty:TreatWarningsAsErrors -getProperty:TargetFramework -getProperty:ManagePackageVersionsCentrally
dotnet msbuild App.fsproj -getItem:Compile
dotnet restore App.fsproj
dotnet package list --project App.fsproj --include-transitive
dotnet tool list --local
```

`-getItem:Compile` reports the evaluated compilation sequence, including imports. A multi-targeted project needs another property query with `-property:TargetFramework=<tfm>` for the affected target. Replace `<tfm>` with a declared framework.

An empty `LangVersion` property means no evaluated override. Check the selected compiler's default rather than treating the empty value as a language version.

The package list reports resolved `FSharp.Core`. For conditional dependencies or unexpected resolution, inspect the affected target in `obj/project.assets.json`. Do not infer the library version from the language version.

For CPM, versions normally belong in `Directory.Packages.props`, while projects contain versionless `PackageReference` items. With Paket, use the repository's Paket workflow. Do not introduce a second package manager.

Inspect `dotnet-tools.json` manifests in the working directory and its ancestors, including the `.config/` location. SDK 10 can create a root-level manifest. Read the repository formatter settings. `dotnet tool restore` restores the declared local tools. It does not choose new versions.

## Triage the first failure

Run the repository gate. When no gate exists, use:

```text
dotnet build App.fsproj
```

Read the earliest diagnostic in compilation order. Fix its cause, rebuild, and then reassess later diagnostics. If source inclusion differs from expectations, query `Compile` items rather than adjusting unrelated types.

Do not silence warnings, weaken tests, or change the toolchain to get a green build.

## Prove tests executed

First identify whether `dotnet test` selects VSTest or MTP. On SDK 10, VSTest is the default unless `global.json` selects MTP. Read [the test setups](ecosystem.md#test-setups) when creating or repairing a runner.

For an MTP project, the project selector is:

```text
dotnet test --project Tests.fsproj
```

Use the configured runner's filter syntax. Check its `--help` before borrowing filters from another runner. MTP and VSTest do not share every option.

Require evidence that the affected tests executed, such as named results or a nonzero executed count. A list of discovered tests, an empty filtered run, and a successful build are insufficient. Record skipped tests separately.

When creating or repairing test discovery, temporarily make one discovered test fail. Confirm a nonzero exit code, restore the assertion, and rerun. This checks the runner's failure propagation.

After behavior checks, run the local formatter's configured scope:

```text
dotnet tool restore
dotnet tool run fantomas -- --check .
```

The equivalent command alias is `dotnet fantomas --check .`. Use the repository's wrapper when it chooses a narrower scope. Run only configured analyzers.

## Probe once, then build the project

Create the probe in a temporary directory outside the repository. Replace the marked placeholder below with the actual absolute source path:

```fsharp
#load "<absolute-source-path>/Library.fs"
printfn "Loaded source"
```

Order multiple `#load` directives by the project's compilation sequence. Load the dependencies needed by the probe and account for the project's references and defines. Do not keep a long-lived FSI session as proof of the current source.

```text
dotnet fsi --exec probe.fsx
```

FSI does not validate the `.fsproj`, its signatures, conditional settings, or test discovery. Build the affected project and run the relevant tests afterward. Delete the probe directory before handoff unless the user asked to retain it.
