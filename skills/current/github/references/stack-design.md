# Stacked pull request design

Scope: dependency invariants, layer planning, branch ownership, same-repository scope, and handoffs before `gh stack` changes local/remote state.

Safe default: one strictly linear stack in one repository; plan bottom→top; one reviewable concern and clear owner per layer. Before creating or mutating a stack, make its graph and local lifecycle authority explicit.

Native association is optional. Recommend it when separate dependent reviews help; ordinary dependent PRs remain valid without the extension. Do not turn a recommendation into required setup or silently create a stack.

Write boundaries: branch creation/rewrites, staging/commits, pushes, PR creation, stack linking, and stack restructuring are separate local/remote writes. Check that existing authorization covers each boundary and affected layer; ask only for missing scope. Afterward re-read local `view --json` and remote PR/stack state.

Ownership handoff: `git-worktrees` owns worktree lifecycle; `autommit` owns staging, commit segmentation, and message policy; external branch managers own their local state. Return to `stack-commands.md` only after this design is sound.

## Model

Stack: ≥2 pull requests in one repository.

```text
trunk (usually main)
  └─ auth-layer       → PR #1 (base: trunk)       bottom
       └─ api-layer    → PR #2 (base: auth-layer)
            └─ ui-layer → PR #3 (base: api-layer) top
```

- Bottom branch targets the chosen trunk; each subsequent branch targets the branch immediately below.
- Dependencies flow upward: a layer may depend on code in itself or below, never above. Histories stay linear; avoid merge commits inside a stack.
- Each PR should be independently reviewable and represent one concern or coherent owner handoff. Put foundational types/schema/auth below dependent endpoints/tests/UI.
- Plan the entire layer map before edits. For each layer name owner, intent, expected commits, parent branch, reviewer boundary, and likely CI/rebase risk.

## Split or refuse

Split dependent work into layers when focused concerns benefit from separate review or ownership handoffs. Keep tightly coupled changes together when splitting adds no review or verification value. Publish unrelated features as independent PRs against trunk, even when they touch nearby files. Do not stack merely to avoid deciding a clean commit boundary.

Refuse or redesign when:

- branches belong to different repositories or forks; cross-fork stacks unsupported;
- the dependency graph branches or cycles instead of forming one linear chain;
- a layer cannot be described as a focused change with a parent branch;
- branch ownership or local manager is ambiguous;
- an uninspected merge queue, protection rule, or release policy requires a different sequence.

Use separate stacks only when each independent outcome needs its own dependent layers. A stack is not a general project plan, deployment order, or substitute for issue/project tracking.

## Branch and PR conventions

Choose stable, concern-encoding names, e.g. `feat/auth-layer`, `feat/api-layer`, `feat/ui-layer`. Confirm repository branch rules and existing naming conventions before naming. Do not rename or reuse a foreign branch for convenience.

For each layer, record:

|Layer|Branch|Parent/base|Owner|Concern|Expected commit(s)|
|---|---|---|---|---|---|
|Bottom|`<branch-1>`|`<trunk>`|`<owner>`|`<foundational change>`|`<commit handoff>`|
|Middle|`<branch-2>`|`<branch-1>`|`<owner>`|`<dependent change>`|`<commit handoff>`|
|Top|`<branch-3>`|`<branch-2>`|`<owner>`|`<dependent change>`|`<commit handoff>`|

Where repository policy allows, every PR title/body should state its layer and dependency. Labels, reviewers, and draft/ready state belong to `collaboration.md`; this reference requires only an observable dependency relationship.

## Local manager and handoffs

1. Inspect existing worktrees and native manager ownership. `git-worktrees` is authoritative for create/assign/remove; never create a second manager beside it.
2. Determine which tool owns history: `autommit` for raw-Git staging and commit segmentation. Do not mix an external manager's writes with raw `git add/commit/rebase`.
3. If `gh stack` owns the local stack, use its branch/navigation/rebase commands. If Jujutsu, Sapling, git-town, or another manager owns local branches, keep that manager authoritative; use `gh stack link` only for remote stack association.
4. Local tracking is shared across linked worktrees. `rebase`, `sync`, and `modify` can rewrite branches in other clean checkouts. Verify ownership and authorization for every affected worktree; clean state alone grants no authority. Do not let a stack operation silently adopt a consumer/foreign worktree.
5. Hand each layer’s exact staged/commit state to `autommit`; do not use `gh stack add -A/-u/-m` as an unreviewed substitute for repository staging policy.

## Before stack commands

Complete read-only checks:

- `gh --version`, `gh auth status`, and installed `gh extension list`;
- verified repository/host, remotes, default/trunk branch, and worktree/manager state;
- current branch, clean/dirty status, in-progress rebase/merge, and existing stack membership via `gh stack view --json` when capability is available;
- branch protection, required checks, merge queue, and contribution rules relevant to the target repository.

If the requested stack capability is missing, disabled, or returns stack exit 9, report the unavailable operation and preserve existing membership. Continue independent ordinary PR work; extension discovery is not a gate on that work.

## Official references

- [About stacked pull requests](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)
- [Stacked PR quickstart](https://docs.github.com/en/pull-requests/get-started/stacked-prs-quickstart)
- [Managing stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/managing-stacked-pull-requests)
- [Using other tools with stacks](https://docs.github.com/en/pull-requests/reference/use-other-tools-with-stacked-pull-requests)
