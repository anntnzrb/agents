---
name: go
description: "Execute a plan with parallel agent orchestration. Activate when user says /go, asks to execute a plan, or requests multi-agent parallelism."
---

# Go Orchestration Skill

Execute the plan using multi-level parallelism.

## Context

- Extract the plan from previous messages (source of truth)
- If a todo-list tool exists, use it as supplementary reference, but prioritize the conversational plan
- Optional arguments provide additional context: $ARGUMENTS

## Step 1 - Analyze dependencies

- Identify independent tasks (can run in parallel)
- Identify dependent tasks (must wait)
- Group into phases; each phase contains only independent tasks

## Step 2 - Orchestrate

- For each phase, spawn multiple subagents concurrently using parallel `spawn_agent` tool calls
- Each subagent prompt must include:
  1. Full context (architectural decisions, patterns, constraints from planning)
  2. Specific task, files, and acceptance criteria
  3. Instruction: "Batch ALL independent tool calls in a single message"
  4. Expected return: "Return only: OK [confirmation] or BLOCKER [blocker]"

## Step 3 - Execute phases

- Phase N: spawn all independent agents in one parallel batch
- Wait for phase completion
- Phase N+1: spawn next batch (may depend on Phase N results)
- On failure: stop, report blocker, await decision

## Rules

- Orchestration only; do not perform file operations directly
- No redundant explanations; the plan is already understood
- Compact output: report phases, agents spawned, and final status
