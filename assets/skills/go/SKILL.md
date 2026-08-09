---
name: go
description: Execute an existing plan with subagents when asked for /go, orchestrate, workflowz, delegation, or parallel agent work.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Go

Execute the existing plan through subagents. The parent agent owns the plan, integration, and final result.

## Workflow

1. Extract every requested item and constraint from the conversation. Do not outsource top-level planning
2. Map dependencies. Dispatch genuinely independent, substantial slices together; keep prerequisites and trivial edits inline
3. Give each subagent a self-contained target, context, constraints, and observable acceptance criteria. Name file overlap and require coordination
4. Continue useful non-overlapping work while agents run. Wait only when a critical-path result blocks progress
5. Integrate results as they arrive. Inspect status, correct or reassign incomplete work, and handle failures individually rather than abandoning the run
6. Verify the combined deliverable end to end. Continue until every requested item is complete or a concrete blocker requires the user

## Rules

- Use the runtime's actual agent tools and lifecycle; do not invent parallel wrappers or assume waiting returns agent output
- Reuse or close agents when supported instead of leaking capacity
- Parent verification is authoritative; subagent self-reports are evidence, not proof
- Do not yield at a phase boundary or ask for confirmation when repository context can decide
