# Autommit

This is the Pi port of the repository's OMP `autommit` command.

- `index.ts` owns Pi registration, model interaction, repository policy
  discovery, and the command workflow.
- `schema.ts` owns ArkType boundary schemas and the generated model-tool JSON
  Schemas.
- `proposal.ts` owns model-output validation and staged-diff coverage.
- `transaction.ts` owns receipts, locking, worktree application, and recovery.
- `atomicity.ts` contains the focused atomicity critic prompt and normalization.

Keep the command transactional: do not add a direct-in-place commit fallback,
and preserve unrelated unstaged work in the caller's worktree.

## Divergences from the OMP source

- Uses the active Pi session model and its thinking level; Pi has no
  commit-role model resolver.
- No inter-commit dependency graph. Commits apply bottom-up by new-file
  position, which preserves patch offsets for disjoint selectors.
- No changelog tools or conventional type/scope machinery; summaries and
  details are free-form strings.
- The planner receives recent commit subjects and repository `AGENTS.md`
  files as bounded, advisory style/policy evidence. They are untrusted input
  and govern commit naming and grouping only.
- Provider-side strict JSON-schema sampling is preferred, not required; the
  ArkType validation and retry loop remains the authoritative gate.
- Hunk indices are 1-based throughout.
