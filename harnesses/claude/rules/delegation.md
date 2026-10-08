# Delegation

This rule applies only to the main conversation. If you are a subagent, ignore it and complete your assigned task yourself.

You direct the session. Keep design, decisions, and subtle edits in this conversation, and delegate self-contained work that would otherwise flood your context:

- Codebase searches that need more than a few reads: Explore.
- Running tests, builds, or linters; digging through logs or docs; mechanical, well-specified edits: general-purpose.

Do quick, targeted lookups of one to three reads yourself. Give each delegate the paths, the goal, and the expected output. Verify its result against the real diff or command output before you build on it. If a delegate fails the same task twice, do it yourself or delegate it again with `model: "opus"`.
