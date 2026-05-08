import type { Theme, ThemeColor } from "@mariozechner/pi-coding-agent";
import { registerFooterContribution } from "../_shared/footer-contributions.js";
import { formatElapsed } from "./format.js";
import { CUSTOM_TYPE } from "./state.js";

type GoalStatus = "active" | "paused" | "complete";

type GoalLike = {
	status: GoalStatus;
	timeUsedSeconds: number;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
	!!value && typeof value === "object";

const getOptionalNumber = (value: unknown): number | undefined =>
	typeof value === "number" && Number.isFinite(value) ? value : undefined;

const getEntryType = (entry: unknown): string | undefined =>
	isRecord(entry) && typeof entry["type"] === "string" ? entry["type"] : undefined;

const getCustomEntryType = (entry: unknown): string | undefined =>
	isRecord(entry) && typeof entry["customType"] === "string" ? entry["customType"] : undefined;

const getCustomEntryData = (entry: unknown): unknown => (isRecord(entry) ? entry["data"] : undefined);

const getGoalFromEntry = (entry: unknown): GoalLike | null | undefined => {
	if (getEntryType(entry) !== "custom" || getCustomEntryType(entry) !== CUSTOM_TYPE) return undefined;
	const data = getCustomEntryData(entry);
	if (!isRecord(data)) return null;
	const goal = data["goal"];
	if (!isRecord(goal)) return null;
	const status = goal["status"];
	if (status !== "active" && status !== "paused" && status !== "complete") return null;
	const timeUsedSeconds = getOptionalNumber(goal["timeUsedSeconds"]);
	if (timeUsedSeconds === undefined) return null;
	return { status, timeUsedSeconds };
};

const getLatestGoal = (entries: readonly unknown[]): GoalLike | null => {
	for (let index = entries.length - 1; index >= 0; index--) {
		const goal = getGoalFromEntry(entries[index]);
		if (goal !== undefined) return goal;
	}
	return null;
};

const getGoalColor = (goal: GoalLike): ThemeColor => {
	if (goal.status === "active") return "success";
	if (goal.status === "paused") return "warning";
	return "dim";
};

const getGoalStatusGlyph = (goal: GoalLike): string => {
	if (goal.status === "active") return "⚑";
	if (goal.status === "paused") return "‖";
	return "✓";
};

const buildGoalBadge = (theme: Theme, goal: GoalLike | null): string | undefined => {
	if (!goal) return undefined;
	return theme.fg(getGoalColor(goal), `${getGoalStatusGlyph(goal)}${formatElapsed(goal.timeUsedSeconds)}`);
};

export const registerGoalFooterContribution = (): void => {
	registerFooterContribution({
		id: "pi-goal",
		render: ({ entries }, theme) => buildGoalBadge(theme, getLatestGoal(entries)),
	});
};

export const __test = {
	buildGoalBadge,
	getLatestGoal,
};
