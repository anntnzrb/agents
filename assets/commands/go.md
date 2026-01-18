---
description: Execute plan with parallel agent orchestration
agent: build
---

Execute the plan using multi-level parallelism.

CONTEXT:

- Extract the plan from previous messages (source of truth)
- Use todo-list (`todoread`) as supplementary reference if it exists, but prioritize the conversational plan
- Optional arguments provide additional context: $ARGUMENTS

STEP 1 - ANALYZE DEPENDENCIES:
Identify from the plan:

- Independent tasks (can run in parallel)
- Dependent tasks (must wait for others)
- Group into phases where each phase contains only independent tasks

STEP 2 - ORCHESTRATE:
For each phase, spawn multiple `general` subagents concurrently using parallel `task` tool calls.

Each subagent prompt MUST include:

1. Full context (architectural decisions, patterns, constraints from our planning)
2. Specific task, files, and acceptance criteria
3. Instruction: "Batch ALL independent tool calls in a single message"
4. Expected return: "Return only: ✅ [confirmation] or ❌ [blocker]"

STEP 3 - EXECUTE PHASES:

- Phase N: Spawn all independent agents in ONE message with parallel tool calls
- Wait for phase completion
- Phase N+1: Spawn next batch (these may depend on Phase N results)
- On failure: Stop, report blocker, await decision

RULES:

- Orchestration only: Do NOT perform file operations directly
- No redundant explanations: The plan is already understood
- Compact output: Report phases, agents spawned, and final status
