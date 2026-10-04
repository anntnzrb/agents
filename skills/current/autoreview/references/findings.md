# Findings contract

Read before writing the file passed to `verify --findings`.

The report is a JSON object with nonempty `summary`, `overall_correctness` equal to
`patch is correct` or `patch is incorrect`, and a `findings` array.

Each finding requires:

- `title`: 1 to 140 characters.
- `body`: 1 to 2000 characters, explaining the trigger, consequence, and correction.
- `priority`: P0, P1, P2, or P3.
- `confidence`: a number from 0 to 1, not a boolean.
- `category`: `bug`, `security`, `regression`, `test_gap`, or `maintainability`.
- `code_location`: an object containing a repository-relative `file_path` and integer `line` starting at 1.

Use forward slashes in `file_path`. Absolute paths, parent traversal, sensitive paths,
and files outside the selected changed files cannot validate.
The referenced source must exist in a reviewed state. Deleted files have no post-change source location.

Add `code_location.excerpt` for a quoted source line. Verification compares the entire
physical line exactly, including whitespace. An empty file uses line 1 and an empty excerpt.
An empty physical line uses its actual line number and an empty excerpt.
Add `code_location.state` to select `INDEX`, `WORKTREE`, or the pinned head SHA printed by the bundle.
Without `state`, a match in any captured state suffices.
Use `excerpt` whenever the body quotes code, so verification can check the quote.
The CLI does not extract quotes from prose or validate the diagnosis itself.

```json
{
  "summary": "The changed divisor fails for every input.",
  "overall_correctness": "patch is incorrect",
  "findings": [
    {
      "title": "Restore the nonzero divisor",
      "body": "Every call now raises ZeroDivisionError. Restore a nonzero divisor.",
      "priority": "P1",
      "confidence": 1.0,
      "category": "bug",
      "code_location": {
        "file_path": "app.py",
        "line": 2,
        "excerpt": "    return n / 0",
        "state": "WORKTREE"
      }
    }
  ]
}
```

All findings are validated before priority filtering. Invalid lower-priority findings
still fail verification. A successful report retains its original overall assessment
even when filtering removes all findings.
