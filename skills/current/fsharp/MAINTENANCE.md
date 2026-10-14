# F# skill maintenance

Maintainer procedure, not routed from `SKILL.md`. Use when refreshing the skill or assessing new content.

## Sources

| Source | Read |
| --- | --- |
| [dotnet/docs](https://github.com/dotnet/docs) | `docs/fsharp/whats-new/fsharp-9.md`, `fsharp-10.md`, and the next released version |
| [NuGet registration API](https://learn.microsoft.com/en-us/nuget/api/registration-base-url-resource) | Version, `catalogEntry.listed`, dependency ranges, and target frameworks |
| [NuGet CPM](https://learn.microsoft.com/en-us/nuget/consume-packages/central-package-management) | Central version ownership and restore behavior |
| [Expecto](https://github.com/haf/expecto) | Runner documentation and release compatibility notes |
| [YoloDev.Expecto.TestSdk](https://github.com/YoloDev/YoloDev.Expecto.TestSdk) | MTP properties, generated entry point, and package compatibility |
| [dotnet test](https://learn.microsoft.com/en-us/dotnet/core/testing/unit-testing-with-dotnet-test) | SDK runner selection and options |
| [xUnit v3](https://xunit.net/docs/getting-started/v3/getting-started) | Executable test projects, MTP integration, and F# discovery |
| [FsCheck](https://github.com/fscheck/FsCheck) | v3 release notes and integration packages |
| [Fantomas](https://github.com/fsprojects/fantomas) | Local-tool invocation and supported syntax |
| [nixpkgs](https://github.com/NixOS/nixpkgs) | SDK and language-server attributes, `buildDotnetModule`, and NuGet dependency generation |
| [F# in Action](https://www.manning.com/books/f-sharp-in-action), Isaac Abraham, 2024 | Background only. The book targets F# 8. The baseline fixtures did not need its design advice |

Write original prose. Do not copy book passages or upstream wording.

## Inclusion bar

Add content only when an executable baseline evaluation exposes a failure, or a verified ecosystem fact can become stale or cannot be inferred from the project.

The initial strong-model baseline solved all ten fixtures without a skill. The only observed hygiene slip was an untracked scratch verification folder. Keep the core workflow short and require probe cleanup.

Do not add generic style, design, syntax lessons, compile-order explanations, signature-file lessons, nullable-boundary recipes, DU exhaustiveness advice, or FsCheck API tutorials. The baseline already handled those. Keep brief operational reminders only where they route detection or verification.

New advice needs a source or a reproducible failure and a task it improves. Package popularity alone is not evidence. A single evaluation run does not justify deleting existing content.

## Refresh upstream facts

1. Resolve stable, listed releases through NuGet registration or `dotnet package search`. Follow registration pagination and inspect `catalogEntry.listed`. Never choose a version from a flat-container index alone.
2. Check the current released F# and .NET versions. Read their what's-new pages and distinguish compiler syntax from `FSharp.Core` APIs.
3. Reproduce the Expecto MTP setup on the declared SDK in a temporary directory. Require executed test counts and a failing sentinel with a nonzero exit code.
4. Verify every changed snippet and command. With Nix available, use `nix shell nixpkgs#dotnet-sdk_10 -c` followed by the command. Check package attributes against the selected nixpkgs revision.
5. Update the verification date and compatibility claims together. Keep versions as a dated snapshot, not automatic upgrade instructions.
6. Apply the skill gate's final authoring review and rerun validation. Delete temporary projects and probes.

Schedule the next release review at F# 11 GA, expected in November 2026. Confirm the actual release before changing greenfield defaults.

## Evaluate the skill

Use the existing `evals/` fixtures and graders. Graders are hidden only when the trial harness exposes the fixture copy without the `evals/graders/` directory. Keep fixture toolchains pinned so baseline and with-skill runs face the same project. Give each run an independent copy of the fixture.

Grader 12 queries NuGet live and requires network access. Grade baseline and with-skill solutions in the same session so package availability is comparable.

From the skill directory, replace `NN` with the grader number and `<solved-dir>` with the completed fixture directory:

```text
dotnet fsi evals/graders/NN.fsx <solved-dir>
```

Compare baseline and with-skill correctness, executed verification, residual scratch files, and unnecessary toolchain or package changes. Inspect transcripts for the decision changed by each instruction. Do not count a claimed check as an executed check.

Retest a proposed deletion across multiple comparable runs. Record fixture results and source evidence in the review, then retain only content that changes behavior or carries a verified ecosystem fact.

## Validate the package

Run from the shared-skills repository root:

```text
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/fsharp
uv run --script skills/current/skill-creator/scripts/cli.py lint skills/current/fsharp
uv run --script skills/current/skill-creator/scripts/cli.py lint
```

The entrypoint stays under 150 lines and routes references through a `Need | Read | When` table. Report unrelated lint findings separately rather than editing another owner's files.
