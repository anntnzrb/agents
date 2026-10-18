# T3c skill maintenance

Maintainer procedure, not loaded by `SKILL.md`. Run it when T3 Code changes its orchestration tools, when a role's model leaves the catalog, or when the user changes role routing.

## Sources

Read the installed T3 build, not memory. The live tool schemas in the harness are authoritative for parameters. `SKILL.md` repeats only the call shape and the caveats that schemas cannot express.

| Source | Where | Read |
| --- | --- | --- |
| T3 orchestration tools | `<T3 home>/runtime/versions/<active version>/t3`, a bundled JavaScript file with `//#region src/...` markers | Tool definitions and the anchors below |
| Active T3 version | `<T3 home>/runtime/service-state.json` | `activeVersion` |
| Live tool schemas | The harness tool list, for example `ToolSearch` with `select:mcp__t3-code__delegate_task` | Input schemas for the tools in the `SKILL.md` Tools table |
| Model catalog | `orchestrator_capabilities` | Provider instance IDs, model IDs, and option IDs for each `roles.toml` target |
| Model benchmarks | The `artificial-analysis-live` skill | Intelligence Index, `costPerTask`, and Terminal-Bench for candidate models |
| Current evidence | The newest `references/model-snapshot-<date>.md` | The dated numbers and reasons behind each `roles.toml` target |

`<T3 home>` is `T3CODE_HOME`, or `~/.t3` when unset.

The bundle is large and partly binary. Search it with `grep -an` and cut long lines. Bundler suffixes such as `make$16` change between builds, so match tool definitions with a pattern:

```bash
grep -anE 'make\$[0-9]+\("(delegate_task|task_status|task_cancel|t3_thread_launch|t3_thread_send|t3_thread_read|t3_thread_interrupt|t3_thread_organize|t3_worktree_status|orchestrator_capabilities)"' <bundle>
```

## Facts the skill relies on

Recheck each fact against its anchor after a T3 update. If one no longer holds, fix `SKILL.md` before anything else.

| Fact in `SKILL.md` | Anchor to search |
| --- | --- |
| A child receives only the task string. `role` adds one prefix line | `function taskPrompt` |
| A child gets T3's orchestration instructions: as system or developer instructions on most drivers, prepended to the first prompt on Cursor and on ACP drivers | `T3_CODE_ORCHESTRATION_INSTRUCTIONS`, then its callers `t3OrchestrationSystemPrompt`, `t3OrchestrationPromptForFirstRun`, and `t3AcpPromptWithInstructions` |
| The `opencode` driver offers the `variant` and `agent` options, and an unknown option ID fails | `optionDescriptors` in the `provider-opencode/src/server/status.ts` region, then `rejected options` |
| An `opencode` child runs the `build` agent, or `plan` in plan mode | `agentFor = ` |
| A child inherits the parent's runtime mode, and outside full access an `opencode` session asks before shell and edit | `function resolveRuntimeMode`, then `sessionRules = (` |
| A child runs in the parent's worktree | `function makeSubagentChildThread`, then `cwd` in `RuntimePolicyV2` |
| An ACP-driver child, such as one on `acpRegistry`, gets the T3 MCP server through the stdio `t3 acp-mcp-bridge` | `acp-mcp-bridge` in the `provider-acp/src/server/adapter.ts` region |
| An async child wakes the parent. A wait child does not wake it until its timeout | `completionWake: input.mode` |
| `watch_pull_request` wakes the thread on checks, comments, or conflicts | the `watch_pull_request` tool description |
| `unwatch_pull_request` returns the thread to the user inbox | the `unwatch_pull_request` tool description |
| A cross-provider target does not inherit options | `resolveTarget` in the `OrchestratorMcpService` region |
| Nothing stops a child from calling `delegate_task` | the `delegateTask` handler, which checks only for an active parent run |
| Reading a terminal result through `t3_thread_read` acknowledges the wake | the `t3_thread_read` tool description |
| `orchestrator_capabilities` output is very large | Call it once and measure the result size |
| A message from the parent to a finished app-owned child creates a fresh task with `completionWake: "always"`, and `t3_thread_send` returns its `taskId`. A message to a running child creates no task | `recordSubagentFollowup`, then `OrchestratorMcpThreadSendResult` |
| `t3_thread_launch` without `workspaceStrategy` selects the project root, not the caller's worktree, and has no idempotency key | the `t3_thread_launch` tool description |
| `t3_thread_launch` accepts `modelSelection` with `instanceId`, `model`, and `options` as an object | `ModelSelectionSource`, then `ProviderOptionSelectionsFromLegacyObject` |
| `t3_thread_organize` archives a thread with `action: "archive"` | `ThreadOrganizeTool` |

## Settled decisions

The user settled decisions 1 to 11 on 2026-10-11 and 12 to 15 on 2026-10-15. A refresh MUST NOT silently reverse them. If evidence argues against one, report it and ask.

1. The orchestrator is the thread the user chats with: Claude Opus 5.5 at medium effort, the only effort the user has for Opus. It never appears in `roles.toml`.
2. No role uses `max` effort.
3. The scout and runner run on the `opencode` driver. The implementer and reviewer run on the `codex` driver. No Anthropic model serves a delegated role.
4. Four roles, ordered by importance: implementer, reviewer, runner, scout. The runner shares the scout's model, because running named commands needs no stronger model. The orchestrator never runs gates, and the implementer runs only one targeted check. Escalation is the implementer's `retry_options`, not a separate role.
5. The scout also takes mechanical and prose edits and reviews of them. The reviewer reviews only code diffs that change behavior.
6. Escalation stops after one retry. The orchestrator then reports to the user instead of taking over the work. Infrastructure failures, such as a driver crash, a transport error, `provider_unavailable`, or `model_unavailable`, do not spend that retry.
7. The scout and runner run Gemini 3.8 Flash on the `opencode` driver, for its wider tool set and its `shell` tool's `background` option. Pi was rejected for its four default tools and blocking `bash`. The native `antigravity` driver was rejected because its own subagents cannot be disabled. Oh-my-pi through the `acpRegistry` driver is the parked alternative.
8. Luna, Haiku, Sonnet, and Sol at low effort are excluded. With Gemini at zero effective cost, the Artificial Analysis frontier dominates them for these roles. Haiku beats Gemini on Terminal-Bench only at `xhigh` effort, which the runner does not need.
9. The orchestrator never blocks a turn. Waiting for a child result through completion wakes or PR status through `watch_pull_request` is allowed; yielding a turn while retaining task ownership is not abandoning the task. The orchestrator unwatches PRs before final handoff.
10. Children share the orchestrator's worktree. Parallel slices need disjoint owned files.
11. Delegation uses T3 tools only.
12. The orchestrator may steer or follow up a child through `t3_thread_send` on its `childThreadId`. Independent review rounds still start with a new `delegate_task`.
13. Delegated threads from `t3_thread_launch` serve multi-round dialogues. Each round ends with a result file, a `t3_thread_send` in `queue` mode to the orchestrator, no running processes, and an idle thread. The orchestrator archives the thread when the dialogue ends.
14. Every delegate runs unattended. Its brief forbids asking the user and routes questions to the orchestrator, forbids production access, external writes, leftover processes, commits, and pushes. Its report starts with a short summary. A report too large for a tool result goes complete to a file under /tmp, and the final message carries the summary and the path; detail is never truncated. The skill stays project-agnostic.
15. The orchestrator is the most expensive model, so it delegates mechanical and trivial work. It may write briefs and notes outside the repository, and edit a file itself when delegating costs more than the edit.

## Refresh procedure

1. Read `activeVersion`, then run the definition search above against that build. Compare each tool's description and parameters with `SKILL.md`.
2. Recheck every row in [Facts the skill relies on](#facts-the-skill-relies-on).
3. Call `orchestrator_capabilities`, filter it for each `roles.toml` target, and confirm the provider instance, model ID, and option values exist.
4. When a new candidate model ships, or the snapshot is more than a month old, fetch fresh data through `artificial-analysis-live`, and write a new `references/model-snapshot-<YYYY-MM-DD>.md` from that data. Never edit an older snapshot. Propose any `roles.toml` change to the user.
5. Dispatch one read-only scout with the `roles.toml` scout target and a brief that reads a known file. Compare its report with the file.
6. Run the checks in `docs/skills.md` under "Validate skill metadata".
