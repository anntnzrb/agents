---
name: swarm
description: "Use when a task should fan out across parallel workers, independent slices, races, or best-of attempts."
license: AGPL-3.0-or-later
---

# Swarm

Fan out N parallel workers. They may cover separate slices, race the same brief, or mix both. The parent waits, aggregates, and returns one report.

Adapted from pstack (Lauren Tan, MIT): Cursor cloud workers replaced with local Task subagents.

## Start

Open a todolist with one entry per phase before launching anything.

1. Frame
2. Fan out
3. Aggregate
4. Report

## Phase A: Frame

1. State the done predicate and the artifact or report the swarm must return.
2. Choose the shape. Partition into slices, race N workers on identical briefs, or mix both. For a race or mixed shape, declare `first pass`, `rank all`, or `best-of` before spawning.
3. Set N from the user or derive it from the shape.
4. Give each worker its own writable output when it writes. Use a worktree, branch, or `<temp-dir>/swarm-<slug>/worker-<n>/`. N workers writing to the same path is shared mutable state and fails on arrival.

## Phase B: Fan out

Spawn all N workers in one message as Task subagents (`subagent_type: general`). Each brief stands alone. Include the goal, scope, exact slice or race arm, how to verify, and what to report. Reports use `PASS`, `ISSUES`, or `BLOCKED` with evidence.

If a worker drops out, proceed with N-1 and note it.

## Phase C: Aggregate

Read the terminal results. For coverage, every required slice needs a result. For a race, apply the selection rule declared up front. Use first pass, rank all, or best-of. Do not paste raw worker dumps.

Keep a compact result table, one-line evidenced issues, and explicit gaps or dropouts.

## Phase D: Report

Return one consolidated in-chat report with the table, issue one-liners, gaps or dropouts, and the race rule when used.
