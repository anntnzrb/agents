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

const PROMPT_SNIPPET = "Run child pi workers for parallel subtasks";

const PROMPT_GUIDELINES = [
	"Use for independent subtasks.",
	"Avoid same-file concurrent edits.",
];

const SpawnPiParams = Type.Object({
	task: Type.Optional(
		Type.String({
			description: "Single task.",
		}),
	),
	tasks: Type.Optional(
		Type.Array(Type.String(), {
			description: `Task list (max ${MAX_PARALLEL_TASKS}).`,
		}),
	),
	cwd: Type.Optional(
		Type.String({
			description: "Working directory.",
		}),
	),
	maxConcurrency: Type.Optional(
		Type.Number({
			description: `Parallel workers (default ${DEFAULT_CONCURRENCY}, max ${MAX_PARALLEL_TASKS}).`,
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
	const tasks = (params.tasks ?? []).map((value: string) => value.trim()).filter(Boolean);
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
					tasks: tasks.map((parallelTask: string, index: number) => ({
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
		description: "Delegate independent subtasks to child pi workers.",
		promptSnippet: PROMPT_SNIPPET,
		promptGuidelines: PROMPT_GUIDELINES,
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

			const runtimeTools = pi.getActiveTools();
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
