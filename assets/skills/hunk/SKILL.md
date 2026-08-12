---
name: hunk
description: "Control live Hunk diff reviews: inspect diffs, navigate hunks, reload content, and add inline comments."
---

# Hunk

Interactive terminal diff viewer; TUI user-owned. NEVER run `hunk diff`, `hunk show`, or other interactive commands directly. Use `hunk session *` through the local daemon. No session → ask user to launch Hunk in their terminal.

## Workflow

`list` → `get --repo .` → `review --repo . --json` (structure first) → add `--include-patch` only if raw diff text is needed → `context` when needed → `navigate` → `reload` if needed → focused `comment add` or batched `comment apply` → summarize. Tell the clearest story, not file order; do not comment on every hunk.

## Session selection

Most session commands accept:
- `--repo <path>` — match loaded repository root; prefer this.
- `<session-id>` — exact ID when multiple sessions share a repository.
- No selector — auto-resolve only when one session exists.

`reload` additionally accepts `--session-path <path>` (live Hunk window working directory) and `--source <path>` (directory for the replacement `diff`/`show` command). `--source` does not select a session; use it only when the selected session is not associated with the checkout. For a normal worktree, select with `--repo <worktree>`. Use `--session-path` only when session selection and reload source differ.

## Inspect

```text
hunk session list [--json]
hunk session get (--repo . | <id>) [--json]
hunk session context (--repo . | <id>) [--json]
hunk session review (--repo . | <id>) [--json] [--include-patch]
```

`get` reports `Path`, `Repo`, `Source`; `--repo` matches `Repo`, `--session-path` matches `Path`. Start with `review --json` for file/hunk structure; add `--include-patch` only when raw unified diff is necessary.

## Navigate

Absolute navigation requires `--file` plus exactly one target:

```text
hunk session navigate --repo . --file src/App.tsx --hunk 2
hunk session navigate --repo . --file src/App.tsx --new-line 372
hunk session navigate --repo . --file src/App.tsx --old-line 355
```

Relative comment navigation needs no file:

```text
hunk session navigate --repo . --next-comment
hunk session navigate --repo . --prev-comment
```

Hunk and line numbers are 1-based. Specify exactly one of `--next-comment` or `--prev-comment`.

## Reload

Pass the Hunk review command after `--`:

```text
hunk session reload --repo . -- diff
hunk session reload --repo . -- diff main...feature -- src/ui
hunk session reload --repo . -- show HEAD~1
hunk session reload --repo . -- show HEAD~1 -- README.md
hunk session reload --repo <worktree> -- diff
hunk session reload --session-path <live-window> --source <other-checkout> -- diff
```

Always put `--` before the nested command. Select with `--repo` or exact session ID; `--source` controls execution directory, not session selection. `--session-path` is only for differing session selection and reload source.

## Comments

```text
hunk session comment add --repo . --file README.md --new-line 103 --summary "Tighten this wording" [--rationale "..."] [--author "agent"] [--focus]
printf '%s\n' '{"comments":[{"filePath":"README.md","newLine":103,"summary":"Tighten this wording"}]}' | hunk session comment apply --repo . --stdin [--focus]
hunk session comment list --repo . [--file README.md] [--type live|all|ai|agent|user]
hunk session comment rm --repo . <comment-id>
hunk session comment clear --repo . --yes [--file README.md]
```

Use `comment add` for one note and `comment apply` for a prepared batch. `comment add` requires `--file`, `--summary`, and exactly one of `--old-line`/`--new-line`. Every batch item requires `filePath`, `summary`, and exactly one target: `hunk`, `hunkNumber`, `oldLine`, or `newLine`. `comment apply --stdin` reads JSON and validates the full batch before mutation. Use `--focus` only to steer the user's view. Quote summaries and rationales defensively.

## Guide a review

For a changeset: inspect with `review --json` before requesting patch text; reload the right content if needed; navigate to the first important file/hunk; explain intent, structure, risk, or a non-obvious follow-up in one focused comment; apply prepared notes as one batch; summarize. Highlight what the user would not readily spot.

`hunk diff` includes untracked files by default. Tracked changes only:

```text
hunk session reload --repo . -- diff --exclude-untracked
```

## Recover from errors

- No visible diff file matches → inspect `context`; reload the expected review if needed.
- No active Hunk sessions → if Hunk is visibly running, localhost may be sandboxed; retry with network or sandbox escalation. Otherwise ask the user to open Hunk.
- Multiple active sessions match → pass the exact session ID.
- No active session matches session path → inspect `Path` with `get` or `list`, then correct `--session-path`.
- Replacement command → put `--` before nested `diff`/`show`.
- Batch comments from stdin JSON → add `--stdin` to `comment apply`.
- Navigation → specify exactly one of `--hunk`, `--old-line`, `--new-line`.
- Relative comment navigation → specify either `--next-comment` or `--prev-comment`, not both.
