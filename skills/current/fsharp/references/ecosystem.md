# F# ecosystem facts

Read before adding or upgrading a package, using a newer feature, or creating a test runner.
Versions below were verified on 2026-10-13. Re-resolve before use. They are evidence, not project pins.

## Resolve listed releases

NuGet's flat-container version index includes unlisted releases. Both `FSharp.Core 11.0.100` and `YoloDev.Expecto.TestSdk 1.0.0` are unlisted in the verified snapshot.

Use a listing-aware command:

```text
dotnet package search FSharp.Core --exact-match
dotnet package search YoloDev.Expecto.TestSdk --exact-match
dotnet list package --outdated
```

On SDK `10.0.401`, exact-match search returned 45 listed stable YoloDev versions, ending at `0.16.1`, and omitted unlisted `1.0.0`. In a restored CPM project pinned to `0.16.0`, `dotnet list package --outdated` reported `0.16.1` as `Latest`, also skipping `1.0.0`. These commands inspect available versions without updating the pins. Search returns multiple versions. Select the highest stable version semantically.

`dotnet add package` also resolves listed releases when no version is supplied. Use it only when a package change is intended and the repository's dependency workflow permits it.

For exact metadata, request `https://api.nuget.org/v3/registration5-gz-semver2/<lowercase-package-id>/index.json`. The package ID is a placeholder. Follow page `@id` links when a page omits embedded `items`. Inspect each leaf's `catalogEntry.version` and `catalogEntry.listed`. Choose a stable version with `listed: true`, then check its dependency ranges and target frameworks. Compare versions semantically, not as strings.

The unlisted YoloDev `1.0.0` requires Expecto `[9,10)`. The listed `0.16.x` series declares Expecto `>= 10.2.3`. A higher version number does not establish compatibility.

## Gate features by the project

F# 10 shipped with .NET 10 LTS in November 2025. As verified on 2026-10-13, F# 11 and .NET 11 are at RC1, with GA expected in November 2026. A preview is not the greenfield default.

Syntax follows the effective `LangVersion`. Library APIs follow the resolved `FSharp.Core`. The installed SDK alone proves neither. Keep the repository's versions and use an older supported form when needed.

| Release | Feature | Gate |
| --- | --- | --- |
| F# 9 | Nullable reference checking | `LangVersion` 9+, with `Nullable` enabled |
| F# 9 | DU `.Is*` properties, bool-returning partial active patterns, empty-bodied computation expressions, attribute-target enforcement | `LangVersion` 9+ |
| F# 9 | Random collection functions | Resolved `FSharp.Core` with the APIs, introduced in 9 |
| F# 9 | C# collection expressions constructing F# lists and sets | Supporting `FSharp.Core` plus the consuming C# compiler |
| F# 10 | Scoped `#nowarn` and `#warnon`, auto-property accessor visibility | `LangVersion` 10+ |
| F# 10 | `[<Struct>]` optional parameters using `ValueOption` | `LangVersion` 10+ |
| F# 10 | `ReturnFromFinal` and `YieldFromFinal` tail calls, typed CE bindings without parentheses, `_` in `use!` | `LangVersion` 10+ and a builder supporting the operations used |
| F# 10 | Warning for ranges with omitted `seq` | `LangVersion` 10+ |
| F# 10 | `and!` in `task` expressions | Resolved `FSharp.Core` 10+ task builder and a compiler accepting the syntax |
| F# 10 | Better trimming, parallel compilation preview, type subsumption cache | Compiler and build tooling, not a reason to change project settings |

For example, task `and!` binds independent operations together. This complete function compiles with F# 10 and `FSharp.Core` 10:

```fsharp
let sumTasks (left: System.Threading.Tasks.Task<int>) (right: System.Threading.Tasks.Task<int>) =
    task {
        let! x = left
        and! y = right
        return x + y
    }
```

Feature sources: [F# 9 changes](https://learn.microsoft.com/en-us/dotnet/fsharp/whats-new/fsharp-9) and [F# 10 changes](https://learn.microsoft.com/en-us/dotnet/fsharp/whats-new/fsharp-10).

## Test setups

### Expecto with MTP

Use this setup when the repository selects `Microsoft.Testing.Platform` in `global.json`, or for the greenfield MTP default. For the default VSTest mode, use the next setup instead.

The following setup was proven on SDK `10.0.401`. Three tests executed successfully. A failing sentinel produced exit code `2`.

Keep any existing SDK policy when adding this `global.json` test selection:

```json
{
    "test": { "runner": "Microsoft.Testing.Platform" }
}
```

For a new CPM project, these are complete example files. The versions reproduce the verified setup. Re-resolve them before adopting the setup.

`Directory.Packages.props`:

```xml
<Project>
    <PropertyGroup>
        <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
    </PropertyGroup>
    <ItemGroup>
        <PackageVersion Include="FSharp.Core" Version="10.1.401" />
        <PackageVersion Include="Expecto" Version="11.1.1" />
        <PackageVersion Include="Expecto.FsCheck" Version="11.1.1" />
        <PackageVersion Include="FsCheck" Version="3.4.0" />
        <PackageVersion Include="YoloDev.Expecto.TestSdk" Version="0.16.1" />
    </ItemGroup>
</Project>
```

Declare `FSharp.Core` centrally and reference it explicitly with CPM. Without that reference, this package graph resolves transitive `FSharp.Core 7.0.200` on SDK 10.0.401.

`Tests.fsproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
    <PropertyGroup>
        <TargetFramework>net10.0</TargetFramework>
        <OutputType>Exe</OutputType>
        <Nullable>enable</Nullable>
        <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
        <EnableExpectoTestingPlatformIntegration>true</EnableExpectoTestingPlatformIntegration>
    </PropertyGroup>
    <ItemGroup>
        <Compile Include="Tests.fs" />
        <PackageReference Include="FSharp.Core" />
        <PackageReference Include="Expecto" />
        <PackageReference Include="Expecto.FsCheck" />
        <PackageReference Include="FsCheck" />
        <PackageReference Include="YoloDev.Expecto.TestSdk" />
    </ItemGroup>
</Project>
```

`Tests.fs`:

```fsharp
module VerificationTests

open Expecto

[<Tests>]
let tests =
    testList "Verification" [
        testCase "unit case" (fun () -> Expect.equal (1 + 1) 2 "sum")
        testCase "sentinel" (fun () -> Expect.isTrue true "runner executes this")
        testProperty "integer identity" (fun (value: int) -> value + 0 = value)
    ]
```

Run `dotnet test --project Tests.fsproj`. YoloDev generates the entry point in this mode. Do not add a manual `[<EntryPoint>]` or `Microsoft.NET.Test.Sdk` to this setup.

### Expecto with VSTest

Use this setup when `global.json` does not select MTP and `dotnet test` uses default VSTest mode. On SDK `10.0.401`, two tests passed with exit code `0`. Changing the sentinel to fail produced one pass, one failure, and exit code `1`.

Use the CPM file above with these verified versions: Expecto `11.1.1`, Expecto.FsCheck `11.1.1`, FsCheck `3.4.0`, YoloDev.Expecto.TestSdk `0.16.1`, and FSharp.Core `10.1.401`. Add `Microsoft.NET.Test.Sdk` version `18.11.0` to its `PackageVersion` entries.

`Tests.fsproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
    <PropertyGroup>
        <TargetFramework>net10.0</TargetFramework>
        <OutputType>Exe</OutputType>
        <IsTestProject>true</IsTestProject>
        <GenerateProgramFile>false</GenerateProgramFile>
    </PropertyGroup>
    <ItemGroup>
        <Compile Include="Tests.fs" />
        <PackageReference Include="FSharp.Core" />
        <PackageReference Include="Expecto" />
        <PackageReference Include="Expecto.FsCheck" />
        <PackageReference Include="FsCheck" />
        <PackageReference Include="Microsoft.NET.Test.Sdk" />
        <PackageReference Include="YoloDev.Expecto.TestSdk" />
    </ItemGroup>
</Project>
```

Keep the `[<Tests>]` declarations in `Tests.fs`. Append the native entry point shown below as its last declaration. Run `dotnet test Tests.fsproj`. Keep the SDK's normal targets and the YoloDev adapter.

### Expecto's native runner

For a native Expecto executable without MTP integration, append this entry point as the last declaration in the last compiled file:

```fsharp
[<EntryPoint>]
let main argv =
    runTestsInAssemblyWithCLIArgs [] argv
```

Use the native runner's options:

```text
dotnet run --project Tests.fsproj -- --summary --fail-on-focused-tests
dotnet run --project Tests.fsproj -- --summary --filter Verification.sentinel
```

Match the hierarchy separator displayed by the runner when using `--filter`. This verified setup uses `.`. These flags belong to Expecto's native runner, not the generated MTP entry point. Require a nonzero executed count for either runner.

### xUnit v3 and property tests

`xunit.v3 4.0.2` uses MTP v2. Its F# project needs `OutputType` set to `Exe` and the same `global.json` MTP selection. The package generates the entry point. A module-level `[<Fact>]` test function takes `()` so it compiles as a method rather than a property.

FsCheck 3's F# modules are in `FsCheck.FSharp`. `Check` remains in `FsCheck`. Arbitrary resolution uses immutable `ArbMap` values rather than global `Arb.register`. Use `FsCheck.Xunit.v3` for xUnit v3 and `Expecto.FsCheck` for Expecto. The latter exposes `testProperty` through `open Expecto`.

TUnit's source-generation requirements need an F# compatibility check before adoption. Its presence on NuGet is not proof that C# examples work in F#.

Runner sources: [dotnet test modes](https://learn.microsoft.com/en-us/dotnet/core/testing/unit-testing-with-dotnet-test), [Expecto](https://github.com/haf/expecto), [YoloDev](https://github.com/YoloDev/YoloDev.Expecto.TestSdk), [xUnit v3](https://xunit.net/docs/getting-started/v3/getting-started), and [FsCheck release notes](https://github.com/fscheck/FsCheck/blob/master/FsCheck%20Release%20Notes.md).

## Package lookup

All version rows are stable, listed releases verified on 2026-10-13. Re-resolve before use. Status describes this snapshot, not a promise of future support.

| Name | Role | Verified version | Status |
| --- | --- | --- | --- |
| FSharp.Core | Language runtime library | 10.1.401 | F# 10 stable line |
| Fantomas | Local formatter | 8.0.8 | Maintained |
| Expecto | Composable test runner | 11.1.1 | Maintained; MTP setup proven |
| Expecto.FsCheck | Expecto property integration | 11.1.1 | Proven with FsCheck 3 |
| YoloDev.Expecto.TestSdk | Expecto test integration | 0.16.1 | Listed; MTP setup proven |
| FsCheck | Property testing | 3.4.0 | Maintained; v3 API |
| xunit.v3 | .NET test framework | 4.0.2 | Maintained; MTP v2 |
| TUnit | Source-generated .NET tests | 1.74.0 | Maintained; F# adoption needs verification |
| Giraffe | Functional ASP.NET Core HTTP handlers | 8.3.0 | Maintained |
| Oxpecker | ASP.NET Core endpoint routing | 2.1.1 | Maintained |
| Fable | F# transpiler for non-.NET targets | 5.21.0 | Maintained; target support varies |
| FsToolkit.ErrorHandling | Result and validation composition | 5.2.0 | Maintained; optional dependency |

## Nix integration

When the repository provides a dev shell, use it. For an isolated SDK 10 check without one:

```text
nix shell nixpkgs#dotnet-sdk_10 -c dotnet --version
nix eval --raw nixpkgs#dotnet-sdk_10.version
nix eval --raw nixpkgs#fsautocomplete.version
```

`fsautocomplete` is the F# language server. Attribute names and versions depend on the selected nixpkgs revision. Query that revision before adding packages.

For packaging, nixpkgs provides the `buildDotnetModule` function. It uses a NuGet dependencies file through `nugetDeps` for offline builds. Follow the repository's existing dependency-file generation workflow. A successful online `dotnet restore` does not verify a Nix package build.
