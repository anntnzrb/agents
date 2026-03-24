import { stat } from "node:fs/promises";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type, type Static } from "@sinclair/typebox";
import { getInheritedCliArgs } from "./cli.js";
import { buildProgressText, buildToolContent, renderCall, renderResult } from "./results.js";
import { getDepthGuard, mapConcurrent, runChildTask } from "./runner.js";
import {
	createChildRunResult,
	didChildRunFail,
	type ChildRunResult,
	type SpawnMode,
	type SpawnPiDetails,
	type TaskSpec,
} from "./types.js";

const MAX_PARALLEL_TASKS = 8;
const DEFAULT_CONCURRENCY = 4;
const UPDATE_THROTTLE_MS = 250;

const SpawnPiParams = Type.Object({
	task: Type.Optional(
		Type.String({
			description:
				"One concrete, self-contained task for a fresh child pi worker. Include all context the child needs in the task itself, because child runs do not inherit session history. Use this for a single delegated worker.",
		}),
	),
	tasks: Type.Optional(
		Type.Array(Type.String(), {
			description: `Independent, self-contained subtasks to run in parallel child pi workers. Use this proactively to maximize throughput when work can be decomposed into bounded parallel units with disjoint responsibilities. Include enough context in each task because child runs start fresh. Max ${MAX_PARALLEL_TASKS}.`,
		}),
	),
	cwd: Type.Optional(
		Type.String({
			description: "Working directory for child pi workers. Defaults to the current cwd so delegated workers stay in the same repo context.",
		}),
	),
	maxConcurrency: Type.Optional(
		Type.Number({
			description: `Maximum parallel child pi workers when using tasks. Default ${DEFAULT_CONCURRENCY}, max ${MAX_PARALLEL_TASKS}. Lower it when subtasks may touch the same files, share git state, or otherwise conflict.`,
			default: DEFAULT_CONCURRENCY,
		}),
	),
});

type SpawnPiParamsInput = Static<typeof SpawnPiParams>;
type TaskPlan = { mode: SpawnMode; tasks: TaskSpec[] };
type TaskPlanResult = { ok: true; value: TaskPlan } | { ok: false; error: string };

const clampConcurrency = (value: unknown): number => {
	if (typeof value !== "number" || !Number.isFinite(value)) return DEFAULT_CONCURRENCY;
	return Math.max(1, Math.min(MAX_PARALLEL_TASKS, Math.trunc(value)));
};

const validateCwd = async (cwd: string): Promise<string | null> => {
	try {
		const info = await stat(cwd);
		return info.isDirectory() ? null : `Invalid cwd "${cwd}": not a directory.`;
	} catch {
		return `Invalid cwd "${cwd}": path does not exist or is not accessible.`;
	}
};

const buildTaskPlan = (
	params: SpawnPiParamsInput,
	cwd: string,
): TaskPlanResult => {
	const task = params.task?.trim();
	const tasks = (params.tasks ?? []).map((value) => value.trim()).filter(Boolean);
	const modeCount = Number(Boolean(task)) + Number(tasks.length > 0);
	if (modeCount !== 1) {
		return { ok: false, error: "Provide exactly one of task or tasks." };
	}
	if (tasks.length > MAX_PARALLEL_TASKS) {
		return {
			ok: false,
			error: `Parallel mode accepts up to ${MAX_PARALLEL_TASKS} tasks.`,
		};
	}

	const taskCwd = params.cwd ?? cwd;
	return task
		? {
				ok: true,
				value: {
					mode: "single",
					tasks: [{ index: 0, task, cwd: taskCwd }],
				},
			}
		: {
				ok: true,
				value: {
					mode: "parallel",
					tasks: tasks.map((parallelTask, index) => ({
						index,
						task: parallelTask,
						cwd: taskCwd,
					})),
				},
			};
};

const createDetails = (taskPlan: TaskPlan): SpawnPiDetails => ({
	mode: taskPlan.mode,
	results: taskPlan.tasks.map(createChildRunResult),
});

const replaceResultAt = (
	results: SpawnPiDetails["results"],
	index: number,
	nextResult: ChildRunResult,
): SpawnPiDetails["results"] =>
	results.map((result, resultIndex) =>
		resultIndex === index ? nextResult : result,
	);

export default function spawnPiExtension(pi: ExtensionAPI) {
	if (getDepthGuard().currentDepth > 0) return;

	const inheritedCliArgs = getInheritedCliArgs();

	pi.registerTool({
		name: "spawn_pi",
		label: "Spawn Pi",
		description: [
			"Delegate work to fresh child pi workers.",
			"Use proactively whenever a request can be broken into independent subtasks, distinct questions, parallel investigation, disjoint codebase slices, or verification work that can run alongside other work.",
			"This tool exists to maximize throughput: when multiple bounded subtasks can advance the main task in parallel, prefer spawning child workers instead of doing everything serially.",
			"Strong signals include requests phrased as parallel, simultaneously, at the same time, concurrently, split this up, fan out, delegate, or separately.",
			"Children inherit the current model, thinking level, cwd, extension set, and built-in tool restrictions, but each child starts fresh with no session carryover.",
			"Use task for one delegated worker and tasks for parallel fanout. Each delegated task should be concrete, well-scoped, self-contained, and explicit about the output needed.",
			"Do not use for tightly coupled steps, urgent critical-path work that blocks the very next action, or concurrent edits to the same files.",
			"Only one spawn level exists: child workers cannot spawn more child workers.",
		].join(" "),
		parameters: SpawnPiParams,

		async execute(_toolCallId, params, signal, onUpdate, ctx) {
			const depth = getDepthGuard();
			if (!depth.canSpawn) {
				return {
					content: [
						{
							type: "text",
							text: `spawn_pi blocked: recursion depth ${depth.currentDepth} reached max ${depth.maxDepth}.`,
						},
					],
					isError: true,
					details: { mode: "single", results: [] } satisfies SpawnPiDetails,
				};
			}

			const taskPlan = buildTaskPlan(params, ctx.cwd);
			if (!taskPlan.ok) {
				return {
					content: [{ type: "text", text: taskPlan.error }],
					isError: true,
					details: { mode: "single", results: [] } satisfies SpawnPiDetails,
				};
			}

			const cwdError = await validateCwd(taskPlan.value.tasks[0]?.cwd ?? ctx.cwd);
			if (cwdError) {
				return {
					content: [{ type: "text", text: cwdError }],
					isError: true,
					details: { mode: taskPlan.value.mode, results: [] } satisfies SpawnPiDetails,
				};
			}

			let details = createDetails(taskPlan.value);
			let lastUpdateAt = 0;
			const emitUpdate = (nextDetails: SpawnPiDetails) => {
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

			const maxConcurrency = clampConcurrency(params.maxConcurrency);
			const results = await mapConcurrent(
				taskPlan.value.tasks,
				maxConcurrency,
				async (taskSpec, index) => {
					const result = await runChildTask({
						taskSpec,
						model: ctx.model,
						thinkingLevel: pi.getThinkingLevel(),
						inheritedCliArgs,
						signal,
						onChange: (partialResult) => updateResult(index, partialResult),
					});
					updateResult(index, result);
					return result;
				},
			);

			const finalDetails: SpawnPiDetails = { ...details, results };
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
