import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type, type Static } from "@sinclair/typebox";
import { getInheritedCliArgs } from "./cli.js";
import {
	buildTaskPlan,
	clampConcurrency,
	DEFAULT_CONCURRENCY,
	MAX_TASKS,
	selectRuntimeTools,
	validateCwd,
} from "./planning.js";
import { buildProgressText, buildToolContent, renderCall, renderResult } from "./results.js";
import { getDepthGuard, killActiveChildProcesses, mapConcurrent, runChildTask } from "./runner.js";
import {
	createChildRunResult,
	didChildRunFail,
	type ChildRunResult,
	type ToolDetails,
	type TaskSpec,
} from "./types.js";

const UPDATE_THROTTLE_MS = 250;

const PROMPT_SNIPPET = "Delegate bounded independent subtasks to child Pi workers";

const PROMPT_GUIDELINES = [
	"Use shard to offload bounded subtasks while the parent remains orchestrator.",
	"Pass all work through tasks, even for one child task.",
	"Only put mutually independent tasks in one shard call; all tasks in the array may run concurrently.",
	"For dependent work, call shard in phases and include prior results in later task prompts.",
	"Omit mode for the default behavior: one task becomes worker, multiple tasks become explorer.",
	"Use mode:'explorer' for parallel read-only codebase inspection.",
	"Use mode:'worker' for a single delegated implementation, validation, or repair task.",
	"Do not use worker mode with multiple tasks; parallel worker isolation is not implemented.",
	"Use timeoutSec only when the child run should be time-bounded.",
	"Use maxTurns or maxToolCalls only for explicit budget limits; omit them for normal exploration or implementation.",
];

const ToolParams = Type.Object({
	tasks: Type.Array(Type.String(), {
		description: `Independent child task batch; max ${MAX_TASKS}. All tasks in one call may run concurrently.`,
		minItems: 1,
		maxItems: MAX_TASKS,
	}),
	mode: Type.Optional(
		Type.String({
			description:
				"Child capability mode: worker or explorer. Omit to derive: one task => worker, multiple tasks => explorer.",
		}),
	),
	cwd: Type.Optional(
		Type.String({
			description: "Working directory for all tasks",
		}),
	),
	maxConcurrency: Type.Optional(
		Type.Number({
			description: `Parallel explorer workers; default ${DEFAULT_CONCURRENCY}, max ${MAX_TASKS}`,
			default: DEFAULT_CONCURRENCY,
		}),
	),
	timeoutSec: Type.Optional(
		Type.Number({
			description: "Optional per-child timeout in seconds; no default",
		}),
	),
	maxTurns: Type.Optional(
		Type.Number({
			description: "Optional per-child maximum assistant turns; no default. Use only for explicit budget limits.",
		}),
	),
	maxToolCalls: Type.Optional(
		Type.Number({
			description: "Optional per-child maximum tool calls; no default. Use only for explicit budget limits.",
		}),
	),
});

type ToolParamsInput = Static<typeof ToolParams>;
type TaskPlan = { mode: "single" | "parallel"; childMode: "worker" | "explorer"; tasks: TaskSpec[] };

const createEmptyDetails = (childMode: "worker" | "explorer" = "worker"): ToolDetails => ({
	mode: "single",
	childMode,
	results: [],
});

const createDetails = (taskPlan: TaskPlan): ToolDetails => ({
	mode: taskPlan.mode,
	childMode: taskPlan.childMode,
	results: taskPlan.tasks.map(createChildRunResult),
});

const replaceResultAt = (
	results: ToolDetails["results"],
	index: number,
	nextResult: ChildRunResult,
): ToolDetails["results"] =>
	results.map((result, resultIndex) =>
		resultIndex === index ? nextResult : result,
	);

export default function shardExtension(pi: ExtensionAPI) {
	if (getDepthGuard().currentDepth > 0) return;

	pi.on("session_shutdown", () => {
		killActiveChildProcesses("SIGTERM");
	});

	const inheritedCliArgs = getInheritedCliArgs();

	pi.registerTool({
		name: "shard",
		label: "shard",
		description:
			"Delegate bounded work to child Pi processes. The parent remains orchestrator. `tasks` is an independent batch: all tasks in one call may run concurrently. Use multiple shard calls for dependent phases.",
		promptSnippet: PROMPT_SNIPPET,
		promptGuidelines: PROMPT_GUIDELINES,
		parameters: ToolParams,

		async execute(_toolCallId, params: ToolParamsInput, signal, onUpdate, ctx) {
			const depth = getDepthGuard();
			if (!depth.canRun) {
				return {
					content: [
						{
							type: "text",
							text: `shard blocked: recursion depth ${depth.currentDepth} reached max ${depth.maxDepth}.`,
						},
					],
					isError: true,
					details: createEmptyDetails(),
				};
			}

			const taskPlan = buildTaskPlan(params, ctx.cwd);
			if (!taskPlan.ok) {
				return {
					content: [{ type: "text", text: taskPlan.error }],
					isError: true,
					details: createEmptyDetails(),
				};
			}

			const cwdError = await validateCwd(taskPlan.value.tasks[0]?.cwd ?? ctx.cwd);
			if (cwdError) {
				return {
					content: [{ type: "text", text: cwdError }],
					isError: true,
					details: {
						mode: taskPlan.value.mode,
						childMode: taskPlan.value.childMode,
						results: [],
					} satisfies ToolDetails,
				};
			}

			let details = createDetails(taskPlan.value);
			let lastUpdateAt = 0;
			const emitUpdate = (nextDetails: ToolDetails) => {
				if (!onUpdate) return;
				const now = Date.now();
				if (now - lastUpdateAt < UPDATE_THROTTLE_MS) return;
				lastUpdateAt = now;
				onUpdate({
					content: [{ type: "text", text: buildProgressText(nextDetails) }],
					details: nextDetails,
				});
			};

			const updateResult = (index: number, nextResult: ChildRunResult) => {
				details = {
					...details,
					results: replaceResultAt(details.results, index, nextResult),
				};
				emitUpdate(details);
			};

			const runtimeTools = selectRuntimeTools(taskPlan.value.childMode, pi.getActiveTools());
			const maxConcurrency = clampConcurrency(params.maxConcurrency);
			const results = await mapConcurrent(
				taskPlan.value.tasks,
				maxConcurrency,
				async (taskSpec, index) => {
					const model = ctx.model as { provider?: string; id?: string } | null | undefined;
					const result = await runChildTask({
						taskSpec,
						...(model !== undefined ? { model } : {}),
						thinkingLevel: pi.getThinkingLevel(),
						inheritedCliArgs,
						runtimeTools,
						signal,
						onChange: (partialResult) => updateResult(index, partialResult),
					});
					updateResult(index, result);
					return result;
				},
			);

			const finalDetails: ToolDetails = { ...details, results };
			const toolContent = await buildToolContent(finalDetails);
			const failed = results.some(didChildRunFail);
			return {
				content: [{ type: "text", text: toolContent.text }],
				isError: failed,
				details: toolContent.details,
			};
		},

		renderCall(args, theme, _context) {
			return renderCall(args, theme);
		},

		renderResult(result, options, theme, _context) {
			return renderResult(result, options, theme);
		},
	});
}
