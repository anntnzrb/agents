import { stat } from "node:fs/promises";
import type { ChildMode, TaskSpec } from "./types.js";

export const MAX_TASKS = 8;
export const DEFAULT_CONCURRENCY = 4;
export const MAX_TIMEOUT_SEC = 86400;

const EXPLORER_TOOLS = new Set(["read", "grep", "find"]);

export type TaskPlan = {
	mode: "single" | "parallel";
	childMode: ChildMode;
	tasks: TaskSpec[];
};

export type PlanResult<T> = { ok: true; value: T } | { ok: false; error: string };

export type PlanInput = {
	tasks?: unknown;
	mode?: unknown;
	cwd?: unknown;
	maxConcurrency?: unknown;
	timeoutSec?: unknown;
};

export const clampConcurrency = (value: unknown): number => {
	if (typeof value !== "number" || !Number.isFinite(value)) return DEFAULT_CONCURRENCY;
	return Math.max(1, Math.min(MAX_TASKS, Math.trunc(value)));
};

export const normalizeTasks = (rawTasks: unknown): PlanResult<string[]> => {
	if (!Array.isArray(rawTasks) || rawTasks.length === 0) {
		return { ok: false, error: "Provide tasks with at least one non-empty task string." };
	}
	if (rawTasks.length > MAX_TASKS) {
		return { ok: false, error: `shard accepts up to ${MAX_TASKS} tasks.` };
	}

	const tasks: string[] = [];
	for (let index = 0; index < rawTasks.length; index += 1) {
		const task = rawTasks[index];
		if (typeof task !== "string") {
			return { ok: false, error: `tasks[${index}] must be a non-empty string.` };
		}
		const trimmed = task.trim();
		if (!trimmed) {
			return { ok: false, error: `tasks[${index}] must be a non-empty string.` };
		}
		tasks.push(trimmed);
	}

	return { ok: true, value: tasks };
};

export const normalizeChildMode = (
	rawMode: unknown,
	taskCount: number,
): PlanResult<ChildMode> => {
	if (rawMode === undefined) {
		return { ok: true, value: taskCount === 1 ? "worker" : "explorer" };
	}
	if (rawMode === "worker" || rawMode === "explorer") {
		return { ok: true, value: rawMode };
	}
	return { ok: false, error: `Invalid mode "${String(rawMode)}". Expected "worker" or "explorer".` };
};

export const validateTimeoutSec = (value: unknown): PlanResult<number | undefined> => {
	if (value === undefined) return { ok: true, value: undefined };
	if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
		return { ok: false, error: "timeoutSec must be a positive finite number of seconds." };
	}
	if (value > MAX_TIMEOUT_SEC) {
		return { ok: false, error: `timeoutSec must be <= ${MAX_TIMEOUT_SEC} seconds.` };
	}
	return { ok: true, value };
};

export const buildTaskPlan = (
	params: PlanInput,
	defaultCwd: string,
): PlanResult<TaskPlan> => {
	const tasks = normalizeTasks(params.tasks);
	if (!tasks.ok) return tasks;

	const childMode = normalizeChildMode(params.mode, tasks.value.length);
	if (!childMode.ok) return childMode;

	if (childMode.value === "worker" && tasks.value.length > 1) {
		return {
			ok: false,
			error:
				"worker mode accepts exactly one task. Use explorer mode for parallel read-only fanout. Parallel worker execution requires future isolation such as worktrees.",
		};
	}

	const timeoutSec = validateTimeoutSec(params.timeoutSec);
	if (!timeoutSec.ok) return timeoutSec;

	const cwd = typeof params.cwd === "string" && params.cwd.trim() ? params.cwd : defaultCwd;

	return {
		ok: true,
		value: {
			mode: tasks.value.length === 1 ? "single" : "parallel",
			childMode: childMode.value,
			tasks: tasks.value.map((task, index) => ({
				index,
				task,
				cwd,
				childMode: childMode.value,
				...(timeoutSec.value !== undefined ? { timeoutSec: timeoutSec.value } : {}),
			})),
		},
	};
};

export const selectRuntimeTools = (
	childMode: ChildMode,
	runtimeTools: readonly string[],
): readonly string[] => {
	if (childMode === "worker") return runtimeTools;
	return runtimeTools.filter((tool) => EXPLORER_TOOLS.has(tool));
};

export const validateCwd = async (cwd: string): Promise<string | null> => {
	try {
		const info = await stat(cwd);
		return info.isDirectory() ? null : `Invalid cwd "${cwd}": not a directory.`;
	} catch {
		return `Invalid cwd "${cwd}": path does not exist or is not accessible.`;
	}
};
