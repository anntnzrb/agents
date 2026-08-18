import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { Effect, Schedule } from "effect";
import { VERSION } from "@earendil-works/pi-coding-agent";
import type {
  ExtensionAPI,
  Theme,
  ThemeColor,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { getFooterContributions } from "../_shared/footer-contributions.js";

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

const DIRTY_CHECK_MS = 15_000;

const separator = (theme: Theme): string => theme.fg("dim", " · ");

const formatNumber = (value: number): string => {
  if (value < 1_000) return value.toString();
  if (value < 10_000) return `${(value / 1_000).toFixed(1)}k`;
  if (value < 1_000_000) return `${Math.round(value / 1_000)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
};

const formatSignedNumber = (value: number): string =>
  value < 0 ? `-${formatNumber(Math.abs(value))}` : formatNumber(value);

const getHomeDir = (): string | undefined =>
  process.env["HOME"] ?? process.env["USERPROFILE"];

const shortenCwd = (cwd: string, home: string | undefined): string =>
  home && cwd.startsWith(home) ? `~${cwd.slice(home.length)}` : cwd;

const getThinkingLabel = (
  model: ModelLike | undefined,
  thinkingLevel: string,
): string => {
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

const getContextLabel = (
  theme: Theme,
  usage: ContextUsageLike | undefined,
  model: ModelLike | undefined,
): string => {
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
  if (!isRecord(value) || typeof value["id"] !== "string") return undefined;
  const model: ModelLike = {
    id: value["id"],
  };
  const contextWindow = getOptionalNumber(value["contextWindow"]);
  if (contextWindow !== undefined) {
    model.contextWindow = contextWindow;
  }
  const reasoning = getOptionalBoolean(value["reasoning"]);
  if (reasoning !== undefined) {
    model.reasoning = reasoning;
  }
  return model;
};

const getContextUsage = (value: unknown): ContextUsageLike | undefined => {
  if (!isRecord(value)) return undefined;
  const tokens = getOptionalNumber(value["tokens"]);
  const contextWindow = getOptionalNumber(value["contextWindow"]);
  if (tokens === undefined || contextWindow === undefined) return undefined;
  return {
    tokens,
    contextWindow,
    percent: getOptionalNumber(value["percent"]) ?? null,
  };
};

const getEntryType = (entry: unknown): string | undefined =>
  isRecord(entry) && typeof entry["type"] === "string"
    ? entry["type"]
    : undefined;

const getCompactionSummary = (entry: unknown): string | undefined =>
  isRecord(entry) && typeof entry["summary"] === "string"
    ? entry["summary"]
    : undefined;

const getCompactionDetailsReserve = (settings: unknown): number | undefined => {
  if (!isRecord(settings)) return undefined;
  const compaction = settings["compaction"];
  if (!isRecord(compaction)) return undefined;
  const reserveTokens = getOptionalNumber(compaction["reserveTokens"]);
  return reserveTokens !== undefined && reserveTokens >= 0
    ? reserveTokens
    : undefined;
};

const readJsonFileEffect = (path: string): Effect.Effect<unknown | undefined> =>
  Effect.tryPromise({
    try: () => readFile(path, "utf8"),
    catch: () => undefined,
  }).pipe(
    Effect.map((text) => (text ? JSON.parse(text) : undefined)),
    Effect.orElseSucceed(() => undefined),
  );

const readReserveTokensEffect = (cwd: string): Effect.Effect<number | undefined> =>
  Effect.gen(function*() {
    const homeDir = getHomeDir();
    const globalSettingsPath = homeDir
      ? join(homeDir, ".pi", "agent", "settings.json")
      : undefined;
    const projectSettingsPath = join(cwd, ".pi", "settings.json");

    const globalJson = globalSettingsPath
      ? yield* readJsonFileEffect(globalSettingsPath)
      : undefined;
    const projectJson = yield* readJsonFileEffect(projectSettingsPath);

    const globalReserve = getCompactionDetailsReserve(globalJson);
    const projectReserve = getCompactionDetailsReserve(projectJson);
    return projectReserve ?? globalReserve;
  });

const getMessageFromEntry = (
  entry: unknown,
): Record<string, unknown> | undefined => {
  if (!isRecord(entry)) return undefined;
  const message = entry["message"];
  return isRecord(message) ? message : undefined;
};

const calculatePollutionPercent = (summary: string): number | null => {
  if (summary.length === 0) return null;
  const blocks = summary.match(
    /<read-files>[\s\S]*?<\/read-files>|<modified-files>[\s\S]*?<\/modified-files>/g,
  );
  if (!blocks || blocks.length === 0) return 0;
  const fileBlockChars = blocks.reduce(
    (total, block) => total + block.length,
    0,
  );
  return Math.round((100 * fileBlockChars) / summary.length);
};

const getMean = (values: readonly number[]): number | null => {
  if (values.length === 0) return null;
  const sum = values.reduce((total, value) => total + value, 0);
  return Math.round(sum / values.length);
};

const computeSessionHealthMetrics = (
  entries: readonly unknown[],
): SessionHealthMetrics => {
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
    if (!message || message["role"] !== "assistant") continue;
    if (typeof message["errorMessage"] !== "string") continue;
    if (message["errorMessage"].includes("context_length_exceeded")) {
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
  footerBadges: readonly string[],
): string[] => {
  const badges: string[] = [...footerBadges];
  const headroom = getCompactionHeadroom(usage, model, reserveTokens);
  if (headroom !== null && shouldShowHeadroomBadge(headroom, reserveTokens)) {
    badges.push(
      theme.fg(getHeadroomColor(headroom), `🪫${formatSignedNumber(headroom)}`),
    );
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
    badges.push(
      theme.fg(getPollutionColor(), `📂${metrics.pollutionPercent}%`),
    );
  }
  if (metrics.overflowCount > 0) {
    badges.push(theme.fg(getOverflowColor(), `💥${metrics.overflowCount}`));
  }
  return badges;
};

const readGitStatusEffect = (cwd: string): Effect.Effect<GitStatus> =>
  Effect.tryPromise({
    try: () =>
      new Promise<string>((resolve, reject) => {
        execFile("git", ["status", "--porcelain"], { cwd, encoding: "utf8" }, (error, stdout) => {
          if (error) reject(error);
          else resolve(stdout);
        });
      }),
    catch: () => "",
  }).pipe(
    Effect.map((output) => ({ isDirty: output.trim().length > 0 })),
    Effect.orElseSucceed(() => ({ isDirty: false })),
  );

const createGitStatusTracker = (
  cwd: string,
  onChange: () => void,
  unsubscribeBranch: () => void,
): GitStatusTracker => {
  let status: GitStatus = { isDirty: false };
  let disposed = false;

  const refreshEffect = readGitStatusEffect(cwd).pipe(
    Effect.tap((nextStatus) =>
      Effect.sync(() => {
        if (disposed || nextStatus.isDirty === status.isDirty) return;
        status = nextStatus;
        onChange();
      }),
    ),
  );

  const loopEffect = refreshEffect.pipe(
    Effect.repeat(Schedule.spaced(DIRTY_CHECK_MS)),
  );

  const fiber = Effect.runFork(loopEffect);

  return {
    getStatus: () => status,
    refresh() {
      if (!disposed) Effect.runFork(refreshEffect);
    },
    dispose() {
      disposed = true;
      fiber.interruptUnsafe();
      unsubscribeBranch();
    },
  };
};

const getDirtyMarker = (theme: Theme, gitStatus: GitStatus): string =>
  gitStatus.isDirty ? theme.fg("warning", "*") : "";

const buildLeft = (
  theme: Theme,
  cwd: string,
  branch: string | null,
  gitStatus: GitStatus,
): string => {
  const versionPrefix = theme.fg("dim", `[v${VERSION}]`) + separator(theme);
  const shortCwd = theme.fg("muted", cwd);
  if (!branch) return versionPrefix + shortCwd;
  return (
    versionPrefix +
    shortCwd +
    separator(theme) +
    theme.fg("accent", branch) +
    getDirtyMarker(theme, gitStatus)
  );
};

const buildRight = (
  theme: Theme,
  usage: ContextUsageLike | undefined,
  model: ModelLike | undefined,
  thinkingLevel: string,
  metrics: SessionHealthMetrics,
  reserveTokens: number | undefined,
  footerBadges: readonly string[],
): string => {
  const base =
    getContextLabel(theme, usage, model) +
    separator(theme) +
    theme.fg("toolTitle", getThinkingLabel(model, thinkingLevel));
  const badges = buildHealthBadges(
    theme,
    usage,
    model,
    metrics,
    reserveTokens,
    footerBadges,
  );
  if (badges.length === 0) return base;
  return `${base}${separator(theme)}${badges.join(separator(theme))}`;
};

const renderFooterLine = (
  left: string,
  right: string,
  width: number,
): string => {
  const padding = " ".repeat(
    Math.max(1, width - visibleWidth(left) - visibleWidth(right)),
  );
  return truncateToWidth(left + padding + right, width);
};

const isStaleExtensionError = (error: unknown): boolean =>
  error instanceof Error &&
  error.message.includes("stale after session replacement or reload");

export const __test = {
  calculatePollutionPercent,
  isStaleExtensionError,
};

export default function footerExtension(pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    if (!ctx.hasUI) return;

    const homeDir = getHomeDir();
    const sessionCwd = ctx.cwd;
    const reserveTokens = await Effect.runPromise(readReserveTokensEffect(sessionCwd));
    let sessionCache:
      | {
          key: string;
          entries: readonly unknown[];
          metrics: SessionHealthMetrics;
        }
      | undefined;

    const getSessionSnapshot = (): {
      entries: readonly unknown[];
      metrics: SessionHealthMetrics;
    } => {
      const entries = ctx.sessionManager.getEntries();
      const leafId = ctx.sessionManager.getLeafId() ?? "root";
      const cacheKey = `${entries.length}:${leafId}`;
      if (sessionCache?.key === cacheKey) return sessionCache;
      const metrics = computeSessionHealthMetrics(entries);
      sessionCache = { key: cacheKey, entries, metrics };
      return { entries, metrics };
    };

    ctx.ui.setFooter((tui, theme, footerData) => {
      const gitStatusTracker = createGitStatusTracker(
        sessionCwd,
        () => tui.requestRender(),
        footerData.onBranchChange(() => {
          gitStatusTracker.refresh();
        }),
      );
      let lastGoodLine: string | undefined;

      return {
        dispose() {
          gitStatusTracker.dispose();
        },
        invalidate() {
          // No cached render state.
        },
        render(width: number): string[] {
          try {
            const usage = getContextUsage(ctx.getContextUsage());
            const model = getModel(ctx.model);
            const { entries, metrics } = getSessionSnapshot();
            const footerBadges = getFooterContributions().flatMap(
              (contribution) => contribution.render({ entries }, theme) ?? [],
            );
            const left = buildLeft(
              theme,
              shortenCwd(sessionCwd, homeDir),
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
              footerBadges,
            );
            const line = renderFooterLine(left, right, width);
            lastGoodLine = line;
            return [line];
          } catch (error) {
            if (!isStaleExtensionError(error)) throw error;
            if (lastGoodLine) return [lastGoodLine];
            const left = theme.fg("muted", shortenCwd(sessionCwd, homeDir));
            return [renderFooterLine(left, "", width)];
          }
        },
      };
    });
  });
}
