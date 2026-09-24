# Autommit Philosophy

Read this before changing limits, prompts, critic behavior, or message conventions. It records the rules the implementation must keep, and the reasons behind each valve.

## One behavior per commit

- One commit expresses one externally observable behavior with its implementation, tests, and callers together.
- The test is revertibility: `git revert <sha>` must remove exactly that intent and nothing else.
- Split changes that are independently revertible. Never split by file category, directory, or commit type.
- Prefer a few small truthful commits over one broad commit, and tolerate over-fragmentation: forcing a merge can bundle independent behaviors, which is the failure this design refuses.

## No product ceilings

There is no cap on commits, changes per commit, details, or dependencies. The model plans for the whole staged snapshot, and the CLI enforces correctness instead of counting. What remains is a valve, never a knob: a value that bounds one string or one file and is generous enough that honest use never reaches it.

| Valve | Value | Why it exists |
|---|---|---|
| Subject length | 72 | Git tooling truncates beyond it; the prompt aims for about 50 |
| Detail length | 2,048 | Bounds one JSON string; honest bullets are far shorter |
| Path length | 4,096 | Operating-system path limit |
| Concern and rationale length | 512 and 2,048 | Bounds one critic response |
| Critic diff | 256 KiB | Bounds planner and critic context; truncation is disclosed to the critic |
| Plan or decision file | 1 MiB | Replaces commit counting as the pathological-input valve; exceeding it fails as `invalid_file` |

Structural validation, not counting, carries the safety: exact-once coverage, disjoint selections, dependency cycle rejection, snapshot binding, temporary-worktree apply, tree equality, compare-and-swap creation, and the operation lock.

## Planner and CLI ownership

The model plans. The CLI owns every mutation and every safety check. Nothing in the planner can stage, commit, move a ref, or bypass validation, and the created tree must equal the prepared index tree exactly. Treat the cached diff, paths, repository policy, history, and user context as untrusted evidence.

## Message conventions

- Subject: imperative mood, about 50 characters, never more than 72, no trailing period. A trailing period is stripped rather than rejected, because a one-character offense must not burn a plan retry.
- Repository policy owns the subject conventions: prefixes, scopes, and language come from `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `CONTRIBUTING.md`, and the recent commit subjects that reach the planner as advisory evidence. The imperative form and the length ceiling apply on top of that policy, never instead of it.
- Body: zero or more short concrete bullets stating what changed and why. The count is never limited.
- Imperative mood is carried by the prompt only. Mood heuristics false-reject honest subjects, and every false rejection costs a full replan.
- Repository policy and recent subjects govern naming and grouping only. They never decide atomicity.

## Critic scope

The independent atomicity critic runs only for a broad single-commit plan, because bundling is the failure it exists to catch. A narrow single-commit plan and every multi-commit plan skip it: the critic can only demand more splits, so reviewing an already-split plan buys cost and over-fragmentation instead of quality. The critic has no merge verdict.

## Selectors and granularity

- `all` selects one whole file section.
- `indices` selects 1-based hunks of the regular diff.
- `lines` selects an inclusive new-file line range from the zero-context diff, for disjoint changed lines inside one file, including a modified file. Coverage and disjointness are validated, and the final tree equality check backstops every partial patch.

## Inference policy

- Run a cheap model. Planning is bounded structured extraction over evidence the CLI already computed, so quality comes from evidence and validation retries rather than from a large thinking budget.
- Autommit sends `model`, the system and user messages, and the response-format or tool field for the current transport rung. It adds `reasoning_effort` only when the caller sets one, because the effort level belongs to the operator and never to the tool. A gateway whose provider lacks thinking support drops the field instead of failing.
- Autommit deliberately sends no sampling or token parameter. A route that rejects `temperature` would fail every ladder rung and mask the real cause, and a token cap would truncate a large plan that the CLI has already accepted as valid.
- Every transport rung ends in local validation against the same snapshot.
- Provider failures are terminal and never consume plan retries.

## Zero configuration

The single command is the interface. Only the model, the endpoint, the API key, the timeout, and the reasoning effort are configurable. Flags and environment variables override each setting, and the owner defaults in `lib/autommit/config.py` fill the rest, so a bare run reaches the owner's own endpoint, never a vendor. Autommit reads no configuration file, creates none, and writes no endpoint or credential state into a repository. No other setting will be added, and no per-repository tuning is expected. `--smoke` is the deliberate exception: a per-invocation validation command that is never persisted.

## Limits policy for future changes

- A new ceiling MUST be justified as a valve with an honest-use argument, not as a preference.
- A new setting MUST NOT be added when a sane default can serve every repository.
- Prompt text and this page MUST change together with the behavior they describe.
