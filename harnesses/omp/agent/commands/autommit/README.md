# autommit

`/autommit` runs an unattended local commit agent using the model configured for the OMP `commit` role.

## Purpose

Agents read commit history to understand a codebase. A lumped commit — five
unrelated changes under one vague subject — teaches them nothing and reverts
nothing cleanly. Autommit exists to produce the opposite: a stream of small,
independently-revertible commits, each expressing exactly one externally
observable behavior with its own goal, preconditions, and postconditions.

## Philosophy

- **One behavior per commit.** API, tests, and callers for one behavior stay
  together; independently reversible behaviors split apart, even when they
  share a file or a single Git hunk (disjoint new-file `lines` ranges).
- **Hunks are the unit, not files.** Grouping whole files is trivial; the
  hard part — and this command's core job — is cherry-picking hunks across
  files and unifying the ones that form one revertible unit.
- **Precision over convenience.** More precise commits are always preferable:
  ten atomic commits beat one correct-but-lumped commit, because each one
  can be reviewed, bisected, and reverted on its own.
- **Policy is naming, not grouping.** Repository guidance (`AGENTS.md` and
  friends) is authoritative for commit naming and message format, but never
  decides what counts as atomic — only independent revertibility does.

## How it works

1. **Scope.** If anything is staged, only the staged snapshot is committed
   and unstaged work is left untouched. If nothing is staged, all worktree
   changes are staged first — so a partially-staged tree commits partially,
   while a fully-staged or fully-unstaged tree commits everything.
2. **Proposal.** The commit agent inspects the snapshot and submits either
   one `propose_commit` (indivisible concern) or one `split_commit` plan
   covering every staged hunk exactly once.
3. **Atomicity critic.** Every multi-concern-looking single proposal is
   re-reviewed by an independent critic; a `split` verdict forces a
   multi-commit plan addressing each concern.
4. **Atomic publication.** Split plans are built commit-by-commit in a
   detached worktree, verified tree-for-tree against the staged index, then
   published with a compare-and-swap ref update. A crash-safe receipt plus
   an operation lock mean an interrupted run either recovers or leaves the
   repository untouched — never half-committed.
5. **Cancellation.** If the process receives SIGINT/SIGTERM directly,
   autommit aborts the agent session, releases the operation lock, removes
   temp worktrees, and reports
   `Autommit cancelled; no commits were published.` However, the `omp`
   launcher currently kills the harness process group with SIGKILL on
   Ctrl+C, so in-process cleanup cannot run: the operation lock stays
   behind and the next run reports it as stale, with the exact
   `operation.lock` path to remove. No commits are ever half-published —
   a run either completes its compare-and-swap publication or leaves the
   repository untouched.

## Model selection

Re-evaluate the role before changing its model; provider catalogs, free tiers, quotas, and benchmark results expire quickly.

1. Confirm the exact provider/model selector is available with `omp models <provider> --json`.
2. Confirm the account's current quota and billing behavior with `omp usage`. Treat promotional access, signup credits, and paid balances as non-free unless the provider explicitly lists zero inference cost.
3. Use `skill://artificial-analysis-live` and refresh its live snapshot. For this tool-driven repository workflow, prioritize TerminalBench v2.1, then Automation Bench and the Coding Index. Do not select from the general Intelligence Index alone.
4. Use `skills/deepswe-live/SKILL.md` in the generated agent home, fetch the current supported release, and compare published `pass_at_1`, confidence intervals, agent steps, and output tokens. Preserve model, reasoning effort, harness, and configuration identity.
5. Require benchmark evidence for the exact checkpoint. Do not transfer results from a paid checkpoint to a changing `:free`, `-free`, router, stealth, or `latest` alias.
6. Verify tool calling, structured output, context capacity, latency, privacy terms, retention policy, and rate limits against official provider documentation.
7. Prefer a genuinely free model when its task-relevant evidence is competitive. Otherwise choose the lowest-cost paid model that materially improves end-to-end reliability.
8. Smoke-test the candidate on representative clean, mixed, split, and malformed diffs before making it the default.

The durable configuration is `harnesses/omp/agent/config.yml`. Run the repository sync entrypoint after changing it so the generated OMP home receives the update.
