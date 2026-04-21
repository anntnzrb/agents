import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
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

type SessionHealthMetrics = {
	compactionCount: number;
	overflowCount: number;
	pollutionPercent: number | null;
	pollutionWarnThreshold: number | null;
};

const separator = (theme: Theme): string => theme.fg("dim", " · ");
const DIRTY_POLL_MS = 15_000;

const formatNumber = (value: number): string => {
	if (value < 1_000) return value.toString();
	if (value < 10_000) return `${(value / 1_000).toFixed(1)}k`;
	if (value < 1_000_000) return `${Math.round(value / 1_000)}k`;
	return `${(value / 1_000_000).toFixed(1)}M`;
};

const formatSignedNumber = (value: number): string =>
	value < 0 ? `-${formatNumber(Math.abs(value))}` : formatNumber(value);

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

const getEntryType = (entry: unknown): string | undefined =>
	isRecord(entry) && typeof entry.type === "string" ? entry.type : undefined;

const getCompactionSummary = (entry: unknown): string | undefined =>
	isRecord(entry) && typeof entry.summary === "string" ? entry.summary : undefined;

const getCompactionDetailsReserve = (settings: unknown): number | undefined => {
	if (!isRecord(settings)) return undefined;
	const compaction = settings.compaction;
	if (!isRecord(compaction)) return undefined;
	const reserveTokens = getOptionalNumber(compaction.reserveTokens);
	return reserveTokens !== undefined && reserveTokens >= 0 ? reserveTokens : undefined;
};

const readJsonFile = (path: string): unknown | undefined => {
	try {
		if (!existsSync(path)) return undefined;
		return JSON.parse(readFileSync(path, "utf8"));
	} catch {
		return undefined;
	}
};

const readReserveTokens = (cwd: string): number | undefined => {
	const homeDir = getHomeDir();
	const globalSettingsPath = homeDir ? join(homeDir, ".pi", "agent", "settings.json") : undefined;
	const projectSettingsPath = join(cwd, ".pi", "settings.json");
	const globalReserve = globalSettingsPath
		? getCompactionDetailsReserve(readJsonFile(globalSettingsPath))
		: undefined;
	const projectReserve = getCompactionDetailsReserve(readJsonFile(projectSettingsPath));
	return projectReserve ?? globalReserve;
};

const getMessageFromEntry = (entry: unknown): Record<string, unknown> | undefined => {
	if (!isRecord(entry)) return undefined;
	const message = entry.message;
	return isRecord(message) ? message : undefined;
};

const calculatePollutionPercent = (summary: string): number | null => {
	if (summary.length === 0) return null;
	const blocks = summary.match(
		/<read-files>[\s\S]*?<\/read-files>|<modified-files>[\s\S]*?<\/modified-files>/g,
	);
	if (!blocks || blocks.length === 0) return 0;
	const fileBlockChars = blocks.reduce((total, block) => total + block.length, 0);
	return Math.round((100 * fileBlockChars) / summary.length);
};

const getMean = (values: readonly number[]): number | null => {
	if (values.length === 0) return null;
	const sum = values.reduce((total, value) => total + value, 0);
	return Math.round(sum / values.length);
};

const computeSessionHealthMetrics = (entries: readonly unknown[]): SessionHealthMetrics => {
	let compactionCount = 0;
	let overflowCount = 0;
	const pollutionSeries: number[] = [];

	for (const entry of entries) {
		const entryType = getEntryType(entry);
		if (entryType === "compaction") {
			compactionCount += 1;
			const summary = getCompactionSummary(entry);
			if (summary !== undefined) {
				const pollution = calculatePollutionPercent(summary);
				if (pollution !== null) pollutionSeries.push(pollution);
			}
			continue;
		}
		if (entryType !== "message") continue;
		const message = getMessageFromEntry(entry);
		if (!message || message.role !== "assistant") continue;
		if (typeof message.errorMessage !== "string") continue;
		if (message.errorMessage.includes("context_length_exceeded")) {
			overflowCount += 1;
		}
	}

	const pollutionPercent = pollutionSeries.at(-1) ?? null;
	const pollutionWarnThreshold = getMean(pollutionSeries.slice(0, -1));

	return {
		compactionCount,
		overflowCount,
		pollutionPercent,
		pollutionWarnThreshold,
	};
};

const getCompactionColor = (): ThemeColor => "dim";

const getPollutionColor = (): ThemeColor => "warning";

const getOverflowColor = (): ThemeColor => "warning";

const getHeadroomColor = (headroom: number): ThemeColor =>
	headroom <= 0 ? "error" : "warning";

const getCompactionHeadroom = (
	usage: ContextUsageLike | undefined,
	model: ModelLike | undefined,
	reserveTokens: number | undefined,
): number | null => {
	if (!usage || reserveTokens === undefined) return null;
	const contextWindow = usage.contextWindow || model?.contextWindow;
	if (!contextWindow) return null;
	const threshold = contextWindow - reserveTokens;
	return Math.round(threshold - usage.tokens);
};

const shouldShowHeadroomBadge = (
	headroom: number | null,
	reserveTokens: number | undefined,
): boolean => {
	if (headroom === null || reserveTokens === undefined) return false;
	return headroom < reserveTokens;
};

const buildHealthBadges = (
	theme: Theme,
	usage: ContextUsageLike | undefined,
	model: ModelLike | undefined,
	metrics: SessionHealthMetrics,
	reserveTokens: number | undefined,
): string[] => {
	const badges: string[] = [];
	const headroom = getCompactionHeadroom(usage, model, reserveTokens);
	if (headroom !== null && shouldShowHeadroomBadge(headroom, reserveTokens)) {
		badges.push(theme.fg(getHeadroomColor(headroom), `🪫${formatSignedNumber(headroom)}`));
	}
	if (metrics.compactionCount > 0) {
		badges.push(theme.fg(getCompactionColor(), `✂️${metrics.compactionCount}`));
	}
	if (
		metrics.compactionCount > 0 &&
		metrics.pollutionPercent !== null &&
		metrics.pollutionWarnThreshold !== null &&
		metrics.pollutionPercent > metrics.pollutionWarnThreshold
	) {
		badges.push(theme.fg(getPollutionColor(), `📂${metrics.pollutionPercent}%`));
	}
	if (metrics.overflowCount > 0) {
		badges.push(theme.fg(getOverflowColor(), `💥${metrics.overflowCount}`));
	}
	return badges;
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
	metrics: SessionHealthMetrics,
	reserveTokens: number | undefined,
): string => {
	const base =
		getContextLabel(theme, usage, model) +
		separator(theme) +
		theme.fg("toolTitle", getThinkingLabel(model, thinkingLevel));
	const badges = buildHealthBadges(theme, usage, model, metrics, reserveTokens);
	if (badges.length === 0) return base;
	return `${base}${separator(theme)}${badges.join(separator(theme))}`;
};

const renderFooterLine = (left: string, right: string, width: number): string => {
	const padding = " ".repeat(Math.max(1, width - visibleWidth(left) - visibleWidth(right)));
	return truncateToWidth(left + padding + right, width);
};

export default function footerExtension(pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		if (!ctx.hasUI) return;

		const homeDir = getHomeDir();
		const reserveTokens = readReserveTokens(ctx.cwd);
		let metricsCache: { key: string; value: SessionHealthMetrics } | undefined;

		const getSessionHealthMetrics = (): SessionHealthMetrics => {
			const entries = ctx.sessionManager.getEntries();
			const leafId = ctx.sessionManager.getLeafId() ?? "root";
			const cacheKey = `${entries.length}:${leafId}`;
			if (metricsCache?.key === cacheKey) return metricsCache.value;
			const value = computeSessionHealthMetrics(entries);
			metricsCache = { key: cacheKey, value };
			return value;
		};

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
					const usage = getContextUsage(ctx.getContextUsage());
					const model = getModel(ctx.model);
					const metrics = getSessionHealthMetrics();
					const left = buildLeft(
						theme,
						shortenCwd(ctx.cwd, homeDir),
						footerData.getGitBranch(),
						gitStatusTracker.getStatus(),
					);
					const right = buildRight(
						theme,
						usage,
						model,
						pi.getThinkingLevel(),
						metrics,
						reserveTokens,
					);
					return [renderFooterLine(left, right, width)];
				},
			};
		});
	});
}
