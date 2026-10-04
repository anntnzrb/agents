# Delegation workflows

Each workflow launches agents with zero context. Their prompt is the whole briefing. Choose settings as `SKILL.md` describes before launching.

## Handoff

Transfer the current task to a fresh agent and stop working on it yourself.

Write the briefing with these sections; omit empty ones:

```markdown
## Task
<imperative description>

## Context
<why the task exists>

## Relevant files
- `<path>`: <what it is and why it matters>

## Current state
<done, working, broken>

## What was tried
- <approach>: <why it failed or was abandoned>

## Decisions
- <decision>: <rationale>

## Acceptance criteria
- [ ] <criterion>

## Constraints
- <must not or must preserve>
```

- Preserve the user's intent exactly. Investigate-only work says "Do NOT edit files"; a refactor says "refactor, not rewrite".
- Use a worktree workspace when the user asks for one or the receiver will edit alongside other work.
- Title it `[Handoff] <task>`. Return the agent and workspace IDs to the user. Do not wait for completion.
- The receiver stays your subagent until the user detaches it; detaching is a user action, never an agent call.

## Committee

Two agents analyze a hard problem independently, then converge. Use it when stuck, looping, or planning something difficult.

1. Pick two profiles with contrasting reasoning, from different provider families when possible: one whose notes fit planning or root-cause analysis, one contrasting high-reasoning profile.
2. Write one problem-level prompt. End it with the no-edits suffix below.
3. Launch both in parallel with `[Committee] <task>` titles.
4. Wait for both. Do not send hurry-ups or interrupt; reasoning can take 15 to 30 minutes.
5. Pass each member's arguments to the other until they converge.
6. Report the consensus, where they diverged, and how it resolved.

## Advisor

One agent gives a judgment on the current work; you keep driving.

- Brief it with the sharp question, what you considered and ruled out, and relevant file paths for it to read. Do not paste file contents.
- Ask for a recommendation with its justification. End with the no-edits suffix.
- If the user forwards a skill, such as `/paseo-advisor /unslop`, tell the advisor to load and run that skill against the task.
- Title it `[Advisor] <topic>`. Wait for its reply, then report its verdict next to your own recommendation.
- Keep the advisor for follow-ups only when the user asks; archive it when the topic changes.

## No-edits suffix

```text
This is analysis only. Do NOT edit, create, or delete any files. Do NOT write code.
```
