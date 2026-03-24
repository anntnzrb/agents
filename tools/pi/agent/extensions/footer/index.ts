import { execFileSync } from "node:child_process";
import type { ExtensionAPI, Theme, ThemeColor } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";

type ModelLike = {
	id: string;
	contextWindow?: number;
	reasoning?: boolean;
};

type ContextUsageLike = {
	tokens: number;
	contextWindow: number;
	percent?: number | null;
};

type GitStatus = {
	isDirty: boolean;
};

type GitStatusTracker = {
	getStatus: () => GitStatus;
	refresh: () => void;
	dispose: () => void;
};

const separator = (theme: Theme): string => theme.fg("dim", " · ");
const DIRTY_POLL_MS = 15_000;

const formatNumber = (value: number): string => {
	if (value < 1_000) return value.toString();
	if (value < 10_000) return `${(value / 1_000).toFixed(1)}k`;
	if (value < 1_000_000) return `${Math.round(value / 1_000)}k`;
	return `${(value / 1_000_000).toFixed(1)}M`;
};

const getHomeDir = (): string | undefined => process.env.HOME ?? process.env.USERPROFILE;

const shortenCwd = (cwd: string, home: string | undefined): string =>
	home && cwd.startsWith(home) ? `~${cwd.slice(home.length)}` : cwd;

const getThinkingLabel = (model: ModelLike | undefined, thinkingLevel: string): string => {
	if (!model) return "no-model";
	if (!model.reasoning || thinkingLevel === "off") return model.id;
	return `${model.id} (${thinkingLevel})`;
};

const getContextColor = (usage: ContextUsageLike | undefined): ThemeColor => {
	const percent = usage?.percent ?? 0;
	if (percent > 90) return "error";
	if (percent > 70) return "warning";
	return "success";
};

const getContextLabel = (theme: Theme, usage: ContextUsageLike | undefined, model: ModelLike | undefined): string => {
	const tokens = usage?.tokens ?? 0;
	const contextWindow = usage?.contextWindow ?? model?.contextWindow ?? 0;
	const color = getContextColor(usage);
	return (
		theme.fg(color, formatNumber(tokens)) +
		theme.fg("dim", "/") +
		theme.fg("accent", formatNumber(contextWindow))
	);
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
	!!value && typeof value === "object";

const getOptionalNumber = (value: unknown): number | undefined =>
	typeof value === "number" && Number.isFinite(value) ? value : undefined;

const getOptionalBoolean = (value: unknown): boolean | undefined =>
	typeof value === "boolean" ? value : undefined;

const getModel = (value: unknown): ModelLike | undefined => {
	if (!isRecord(value) || typeof value.id !== "string") return undefined;
	return {
		id: value.id,
		contextWindow: getOptionalNumber(value.contextWindow),
		reasoning: getOptionalBoolean(value.reasoning),
	};
};

const getContextUsage = (value: unknown): ContextUsageLike | undefined => {
	if (!isRecord(value)) return undefined;
	const tokens = getOptionalNumber(value.tokens);
	const contextWindow = getOptionalNumber(value.contextWindow);
	if (tokens === undefined || contextWindow === undefined) return undefined;
	return {
		tokens,
		contextWindow,
		percent: getOptionalNumber(value.percent) ?? null,
	};
};

const readGitStatus = (cwd: string): GitStatus => {
	try {
		const output = execFileSync("git", ["status", "--porcelain"], {
			cwd,
			encoding: "utf8",
			stdio: ["ignore", "pipe", "ignore"],
		});
		return { isDirty: output.trim().length > 0 };
	} catch {
		return { isDirty: false };
	}
};

const createGitStatusTracker = (
	cwd: string,
	onChange: () => void,
	unsubscribeBranch: () => void,
): GitStatusTracker => {
	let status = readGitStatus(cwd);
	const refresh = () => {
		const nextStatus = readGitStatus(cwd);
		if (nextStatus.isDirty === status.isDirty) return;
		status = nextStatus;
		onChange();
	};
	const interval = setInterval(refresh, DIRTY_POLL_MS);
	return {
		getStatus: () => status,
		refresh() {
			status = readGitStatus(cwd);
			onChange();
		},
		dispose() {
			clearInterval(interval);
			unsubscribeBranch();
		},
	};
};

const getDirtyMarker = (theme: Theme, gitStatus: GitStatus): string =>
	gitStatus.isDirty ? theme.fg("warning", "*") : "";

const buildLeft = (theme: Theme, cwd: string, branch: string | null, gitStatus: GitStatus): string => {
	const shortCwd = theme.fg("muted", cwd);
	if (!branch) return shortCwd;
	return shortCwd + separator(theme) + theme.fg("accent", branch) + getDirtyMarker(theme, gitStatus);
};

const buildRight = (
	theme: Theme,
	usage: ContextUsageLike | undefined,
	model: ModelLike | undefined,
	thinkingLevel: string,
): string =>
	getContextLabel(theme, usage, model) +
	separator(theme) +
	theme.fg("toolTitle", getThinkingLabel(model, thinkingLevel));

const renderFooterLine = (left: string, right: string, width: number): string => {
	const padding = " ".repeat(Math.max(1, width - visibleWidth(left) - visibleWidth(right)));
	return truncateToWidth(left + padding + right, width);
};

export default function footerExtension(pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		if (!ctx.hasUI) return;

		const homeDir = getHomeDir();

		ctx.ui.setFooter((tui, theme, footerData) => {
			const gitStatusTracker = createGitStatusTracker(
				ctx.cwd,
				() => tui.requestRender(),
				footerData.onBranchChange(() => {
					gitStatusTracker.refresh();
				}),
			);

			return {
				dispose() {
					gitStatusTracker.dispose();
				},
				invalidate() {
					// No cached render state.
				},
				render(width: number): string[] {
					const left = buildLeft(
						theme,
						shortenCwd(ctx.cwd, homeDir),
						footerData.getGitBranch(),
						gitStatusTracker.getStatus(),
					);
					const right = buildRight(
						theme,
						getContextUsage(ctx.getContextUsage()),
						getModel(ctx.model),
						pi.getThinkingLevel(),
					);
					return [renderFooterLine(left, right, width)];
				},
			};
		});
	});
}
