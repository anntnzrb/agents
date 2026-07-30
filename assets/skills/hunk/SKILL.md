---
name: hunk
description: "Control live Hunk diff reviews: inspect diffs, navigate hunks, reload content, and add inline comments."
---

# Hunk

Hunk is an interactive terminal diff viewer. The TUI belongs to the user. NEVER run `hunk diff`, `hunk show`, or other interactive commands directly. Use `hunk session *` commands to inspect and control live sessions through the local daemon.

If no session exists, ask the user to launch Hunk in their terminal first.

## Workflow

```text
1. hunk session list                                    # find live sessions
2. hunk session get --repo .                            # inspect path / repo / source
3. hunk session review --repo . --json                  # inspect file/hunk structure first
4. hunk session review --repo . --include-patch --json  # opt into raw diff text only when needed
5. hunk session context --repo .                        # check current focus when needed
6. hunk session navigate ...                            # move to the right place
7. hunk session reload -- <command>                     # swap contents if needed
8. hunk session comment add ...                         # leave one review note
9. hunk session comment apply ...                       # apply many agent notes in one stdin batch
```

## Session selection

Most session commands accept:

- `--repo <path>` — match the live session by its loaded repository root; prefer this option
- `<session-id>` — match by exact ID when multiple sessions share a repository
- No selector — auto-resolve when only one session exists

`reload` also supports:

- `--session-path <path>` — match the live Hunk window by its working directory
- `--source <path>` — run the replacement `diff` or `show` command from another directory

Use `--source` only when the selected live session is not already associated with the checkout to load. For a normal worktree session, select it directly with `--repo <worktree>`.

## Inspect

```text
hunk session list [--json]
hunk session get (--repo . | <id>) [--json]
hunk session context (--repo . | <id>) [--json]
hunk session review (--repo . | <id>) [--json] [--include-patch]
```

- `get` reports `Path`, `Repo`, and `Source`. `--repo` matches `Repo`; `--session-path` matches `Path`.
- Start with `review --json`, which returns file and hunk structure. Add `--include-patch` only when raw unified diff text is necessary.

## Navigate

Absolute navigation requires `--file` and exactly one target:

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

- Hunk numbers and line numbers are 1-based.
- Use exactly one of `--next-comment` and `--prev-comment`.

## Reload

Pass a Hunk review command after `--`:

```text
hunk session reload --repo . -- diff
hunk session reload --repo . -- diff main...feature -- src/ui
hunk session reload --repo . -- show HEAD~1
hunk session reload --repo . -- show HEAD~1 -- README.md
hunk session reload --repo <worktree> -- diff
hunk session reload --session-path <live-window> --source <other-checkout> -- diff
```

- Always include `--` before the nested Hunk command.
- Select sessions with `--repo` or an exact session ID.
- `--source` changes where the replacement command runs; it does not select a session.
- Use `--session-path` only when session selection and reload source must differ.

## Comments

```text
hunk session comment add --repo . --file README.md --new-line 103 --summary "Tighten this wording" [--rationale "..."] [--author "agent"] [--focus]
printf '%s\n' '{"comments":[{"filePath":"README.md","newLine":103,"summary":"Tighten this wording"}]}' | hunk session comment apply --repo . --stdin [--focus]
hunk session comment list --repo . [--file README.md] [--type live|all|ai|agent|user]
hunk session comment rm --repo . <comment-id>
hunk session comment clear --repo . --yes [--file README.md]
```

- Use `comment add` for one note and `comment apply` for a prepared batch.
- `comment add` requires `--file`, `--summary`, and exactly one of `--old-line` or `--new-line`.
- Every batch item requires `filePath`, `summary`, and exactly one target: `hunk`, `hunkNumber`, `oldLine`, or `newLine`.
- `comment apply` reads JSON from stdin and validates the full batch before mutation.
- Use `--focus` only when the new note should steer the user's view.
- Quote summaries and rationales defensively.

## Guide a review

When asked to walk through a changeset, inspect structure with `review --json` before requesting patch text. Then:

1. Reload the right content if needed.
2. Navigate to the first important file or hunk.
3. Explain intent, structure, risk, or a non-obvious follow-up in a focused comment.
4. Apply prepared notes as one batch.
5. Summarize the review.

Tell the clearest story rather than following file order. Do not comment on every hunk; highlight what the user would not readily spot.

`hunk diff` includes untracked files by default. To show tracked changes only:

```text
hunk session reload --repo . -- diff --exclude-untracked
```

## Recover from errors

- **No visible diff file matches** — inspect `context`; reload the expected review if needed.
- **No active Hunk sessions** — if Hunk is visibly running, localhost may be sandboxed; retry with network or sandbox escalation. Otherwise ask the user to open Hunk.
- **Multiple active sessions match** — pass the exact session ID.
- **No active Hunk session matches session path** — inspect `Path` with `get` or `list`, then correct `--session-path`.
- **Pass the replacement Hunk command after `--`** — insert `--` before the nested `diff` or `show` command.
- **Pass --stdin to read batch comments from stdin JSON** — add `--stdin` to `comment apply`.
- **Specify exactly one navigation target** — choose one of `--hunk`, `--old-line`, or `--new-line`.
- **Specify either --next-comment or --prev-comment, not both** — choose one direction.
