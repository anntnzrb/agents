# Delegation

This rule applies only to the main conversation. If you are a subagent, ignore it and complete your assigned task yourself.

Inside T3 Code, the `t3c` skill replaces this rule.

You direct the session. Split work by context, not by kind. Every handoff loses detail and adds a round trip. Do work whose context you already hold in this conversation, including edits. Delegate only work that needs little from this conversation and returns a compact result:

- Codebase searches that need more than a few reads: Explore.
- Work whose output would flood your context, such as test, build, or lint runs and digging through logs or docs: general-purpose.
- Independent tasks that run in parallel with fresh context: general-purpose.
- A review you want unanchored by your own read: general-purpose, given the code, not your conclusion.

Do quick, targeted lookups of one to three reads yourself. Give each delegate the paths, the goal, and the expected output. Verify its result against the real diff or command output before you build on it. If a delegate fails the same task twice, do it yourself or delegate it again to a more capable model.
