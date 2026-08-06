# Stacked pull request design

**Covers:** dependency invariants, layer planning, branch ownership, same-repository
scope, and handoffs before `gh stack` changes local or remote state.

**Safe default:** one strictly linear stack in one repository, planned bottom-to-top,
with one reviewable concern and clear owner per layer. Do not create or mutate a
stack until its graph and local lifecycle authority are explicit.

**Write boundary:** branch creation/rewrites, staging/commits, pushes, PR creation,
stack linking, and stack restructuring are separate local/remote writes. Obtain
authorization for each applicable boundary; re-read local `view --json` and remote
PR/stack state afterward.

**Adjacent handoff:** `git-worktrees` owns worktree lifecycle; `commit` owns staging,
commit order, and GitButler-vs-Git engine selection; `gh-contrib` owns contribution
rules, push policy, and ordinary PR creation/review; external branch managers own
their local state. Return to `stack-commands.md` only after this design is sound.

## Model

A stack is two or more pull requests in the same repository:

```text
trunk (usually main)
  └─ auth-layer       → PR #1 (base: trunk)       bottom
       └─ api-layer    → PR #2 (base: auth-layer)
            └─ ui-layer → PR #3 (base: api-layer) top
```

- The bottom branch targets the chosen trunk; every next branch targets the branch
  immediately below it.
- Dependencies flow upward. A layer may depend on code in itself or below it, never
  on a higher layer. Keep histories linear; avoid merge commits inside a stack.
- Each PR should be independently reviewable and represent one concern or coherent
  owner handoff. Put foundational types/schema/auth below endpoints/tests/UI that
  depend on them.
- Plan the entire layer map before edits. Name the owner, intent, expected commits,
  parent branch, reviewer boundary, and likely CI/rebase risk for each layer.

## When to split or refuse a stack

Create a new layer when the concern changes, ownership changes, review can proceed
independently, or a branch is large enough to obscure a smaller diff. Keep unrelated
features in separate stacks even when they touch nearby files. Do not stack merely to
avoid deciding a clean commit boundary.

Refuse or redesign when:

- branches belong to different repositories or forks; cross-fork stacks are not
  supported;
- the dependency graph is branching/cyclic rather than one linear chain;
- a layer cannot be described as a focused change with a parent branch;
- branch ownership or the local manager is ambiguous;
- a merge queue, protection rule, or release policy requires a different sequence that
  has not been inspected.

Use separate stacks for independent work. A single stack is not a general project
plan, deployment order, or substitute for issue/project tracking.

## Branch and PR conventions

Choose names that encode concern and remain stable through review, for example
`feat/auth-layer`, `feat/api-layer`, and `feat/ui-layer`. Confirm repository branch
rules and existing naming conventions before creating names. Do not rename or reuse a
foreign branch because it looks convenient.

For each layer, record:

| Layer | Branch | Parent/base | Owner | Concern | Expected commit(s) |
| --- | --- | --- | --- | --- | --- |
| Bottom | `<branch-1>` | `<trunk>` | `<owner>` | `<foundational change>` | `<commit handoff>` |
| Middle | `<branch-2>` | `<branch-1>` | `<owner>` | `<dependent change>` | `<commit handoff>` |
| Top | `<branch-3>` | `<branch-2>` | `<owner>` | `<dependent change>` | `<commit handoff>` |

Every PR title/body should state its layer and dependency where repository policy
allows. Labels, reviewers, and draft/ready state belong to `gh-contrib`/`collaboration.md`;
this reference only requires the dependency relationship to remain observable.

## Local manager and handoffs

1. Inspect existing worktrees and native manager ownership. `git-worktrees` is the
   authority for create/assign/remove; never create a second manager beside it.
2. Determine whether `commit` selects raw Git or GitButler. Do not mix GitButler
   writes with raw `git add/commit/rebase`.
3. If `gh stack` owns the local stack, use its branch/navigation/rebase commands. If
   Jujutsu, Sapling, git-town, or another manager owns local branches, keep that
   manager authoritative and use `gh stack link` for remote stack association only.
4. Do not make a stack operation silently adopt a consumer/foreign worktree. Preserve
   state when manager or worktree identity is uncertain.
5. Hand each layer's exact staged/commit state to `commit`; do not use `gh stack add
   -A/-u/-m` as an unreviewed substitute for the repository's staging policy.

## Before stack commands

Complete read-only checks:

- `gh --version`, `gh auth status`, and installed `gh extension list`/`gh skill list`;
- verified repository/host, remotes, default/trunk branch, and worktree/manager state;
- current branch, clean/dirty status, in-progress rebase/merge, and existing stack
  membership via `gh stack view --json` when capability is available;
- branch protection, required checks, merge queue, and contribution rules relevant to
  the target repository.

If the extension/feature is missing, preview-only, disabled, or returns stack exit 9,
report availability/rollout rather than silently creating ordinary PRs.

## Official references

- [About stacked pull requests](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)
- [Stacked PR quickstart](https://docs.github.com/en/pull-requests/get-started/stacked-prs-quickstart)
- [Managing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/managing-stacked-pull-requests)
- [Using other tools with stacks](https://docs.github.com/en/pull-requests/reference/use-other-tools-with-stacked-pull-requests)
