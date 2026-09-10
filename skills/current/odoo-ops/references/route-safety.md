# Route safety

Use for static inspection of local addon controllers. Listing a route never authorizes invoking it.

## Commands

```text
uv run --script <skill-dir>/scripts/cli.py routes --json
uv run --script <skill-dir>/scripts/cli.py routes <module> --json
```

The CLI scans Python files under the resolved custom addons directory. It does not provide `route list` or `route scan-writes` commands.

## Output

JSON is an array of route objects with `module`, `class_name`, `method`, `route`, `auth`, `methods`, `file`, and `line`.

The scanner does not return a write-risk classification or parse-error inventory. Unreadable or invalid Python files can be skipped. An empty result does not establish absence of routes or risks.

## Review

Read handler source and its callees before assessing effects. Look for ORM mutations, direct SQL, transaction control, external calls, and business methods such as `action_*`. Names and static signals are heuristics, not proof of read-only behavior.

Keep source inspection, database inspection, and route invocation separate. Do not invoke a controller to test whether it writes. For production or RPC interaction, follow [Safety model](safety-model.md); local inspection does not grant that permission.
