/**
 * Custom Footer Extension - shows working directory, git branch, model, context usage, and extension statuses
 */

import type { AssistantMessage } from "@mariozechner/pi-ai";
import type {
  ContextUsage,
  ExtensionAPI,
  SessionEntry,
  Theme,
  ThemeColor,
} from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";

interface BranchSummary {
  lastMessage: Option.Option<AssistantMessage>;
  totalInput: number;
}

interface ModelInfo {
  id: string;
  contextWindow: number;
  reasoning?: boolean;
}

/** Builds the footer separator fragment. */
const separator = (theme: Theme): string => theme.fg("dim", " │ ");

/** Sanitizes status text for single-line display. */
const sanitizeStatusText = (text: string): string => text.replace(/\r|\n|\t/g, " ");

/** Formats large numbers for compact display. */
const formatNumber = (value: number): string => {
  if (value < 1000) return value.toString();
  if (value < 10000) return `${(value / 1000).toFixed(1)}k`;
  if (value < 1000000) return `${Math.round(value / 1000)}k`;
  return `${(value / 1000000).toFixed(1)}M`;
};

const emptySummary: BranchSummary = {
  lastMessage: Option.none(),
  totalInput: 0,
};

/** Updates aggregate summary values from a session entry. */
const updateSummary = (summary: BranchSummary, entry: SessionEntry): BranchSummary => {
  if (entry.type === "message" && entry.message.role === "assistant") {
    const nextMessage = entry.message.stopReason !== "aborted" ? entry.message : summary.lastMessage;
    return {
      ...summary,
      totalInput: summary.totalInput + entry.message.usage.input,
      lastMessage: nextMessage,
    };
  }

  return summary;
};

/** Summarizes the current branch entries for footer stats. */
const summarizeBranchEntries = (entries: readonly SessionEntry[]): BranchSummary =>
  entries.reduce(updateSummary, emptySummary);

/** Computes total context tokens for the last assistant message. */
const getContextTokens = (lastMessage: AssistantMessage | undefined): number => {
  if (!lastMessage) return 0;
  return (
    lastMessage.usage.input +
    lastMessage.usage.output +
    lastMessage.usage.cacheRead +
    lastMessage.usage.cacheWrite
  );
};

/** Reads the model context window size when available. */
const getContextWindow = (model: ModelInfo | undefined): number => model?.contextWindow ?? 0;

/** Formats the model label, including thinking level when active. */
const getModelDisplay = (model: ModelInfo | undefined, thinkingLevel: string): string => {
  if (!model) return "no-model";
  if (model.reasoning && thinkingLevel !== "off") {
    return `${model.id} (${thinkingLevel})`;
  }
  return model.id;
};

/** Shortens the working directory by replacing home with ~. */
const getShortCwd = (cwd: string, home: string | undefined): string =>
  home && cwd.startsWith(home) ? `~${cwd.slice(home.length)}` : cwd;

/** Resolves context stats from usage or fallback calculations. */
const resolveContextStats = (
  usage: ContextUsage | undefined,
  fallbackTokens: number,
  fallbackWindow: number
): { contextTokens: number; contextWindow: number } =>
  usage
    ? { contextTokens: usage.tokens, contextWindow: usage.contextWindow }
    : { contextTokens: fallbackTokens, contextWindow: fallbackWindow };

/** Picks a color based on context usage percentage. */
const getContextColor = (contextTokens: number, contextWindow: number): ThemeColor => {
  const percentValue = contextWindow > 0 ? (contextTokens / contextWindow) * 100 : 0;
  if (percentValue > 90) return "error";
  if (percentValue > 70) return "warning";
  return "success";
};

/** Builds the git branch segment for the footer. */
const buildBranchStr = (branch: string | undefined, theme: Theme): string =>
  branch ? separator(theme) + theme.fg("accent", branch) : "";

/** Builds the extension status segment for the footer. */
const buildStatusStr = (statuses: ReadonlyMap<string, string>, theme: Theme): string => {
  const parts = [...statuses.values()].map(sanitizeStatusText);
  return parts.length > 0 ? separator(theme) + parts.join(separator(theme)) : "";
};

/** Builds the right-hand side of the footer. */
const buildRight = (
  theme: Theme,
  data: {
    contextTokens: number;
    contextWindow: number;
    totalInput: number;
    modelDisplay: string;
  }
): string => {
  const contextColor = getContextColor(data.contextTokens, data.contextWindow);
  const contextDisplay =
    theme.fg(contextColor, formatNumber(data.contextTokens)) +
    theme.fg("dim", "/") +
    theme.fg("accent", formatNumber(data.contextWindow));
  const ioDisplay = data.totalInput ? theme.fg("dim", ` ↑${formatNumber(data.totalInput)}`) : "";
  return contextDisplay + ioDisplay + separator(theme) + theme.fg("toolTitle", data.modelDisplay);
};

/** Pads and truncates the footer line to the target width. */
const renderLine = (left: string, right: string, width: number): string => {
  const pad = " ".repeat(Math.max(1, width - visibleWidth(left) - visibleWidth(right)));
  return truncateToWidth(left + pad + right, width);
};

/** Composes the full footer line from runtime inputs. */
const buildFooterLine = (input: {
  branchEntries: readonly SessionEntry[];
  branch: string | undefined;
  statuses: ReadonlyMap<string, string>;
  contextUsage: ContextUsage | undefined;
  cwd: string;
  home: string | undefined;
  model: ModelInfo | undefined;
  thinkingLevel: string;
  width: number;
  theme: Theme;
}): string =>
  pipe(
    input,
    (data) => ({
      ...data,
      summary: summarizeBranchEntries(data.branchEntries),
    }),
    (data) => {
      const { contextTokens, contextWindow } = resolveContextStats(
        data.contextUsage,
        getContextTokens(data.summary.lastMessage),
        getContextWindow(data.model)
      );
      const modelDisplay = getModelDisplay(data.model, data.thinkingLevel);
      const shortCwd = getShortCwd(data.cwd, data.home);

      const left =
        data.theme.fg("muted", shortCwd) +
        buildBranchStr(data.branch, data.theme) +
        buildStatusStr(data.statuses, data.theme);

      const right = buildRight(data.theme, {
        contextTokens,
        contextWindow,
        totalInput: data.summary.totalInput,
        modelDisplay,
      });

      return renderLine(left, right, data.width);
    }
  );
  const modelDisplay = getModelDisplay(input.model, summary.thinkingLevel);
  const shortCwd = getShortCwd(input.cwd, input.home);

  const left =
    input.theme.fg("muted", shortCwd) +
    buildBranchStr(input.branch, input.theme) +
    buildStatusStr(input.statuses, input.theme);

  const right = buildRight(input.theme, {
    contextTokens,
    contextWindow,
    totalInput: summary.totalInput,
    modelDisplay,
  });

  return renderLine(left, right, input.width);
};

/** Registers the footer extension with pi. */
const footerExtension = (pi: ExtensionAPI): void => {
  pi.on("session_start", (_event, ctx) => {
    if (!ctx.hasUI) return;
    ctx.ui.setFooter((tui, theme, footerData) => {
      const unsub = footerData.onBranchChange(() => tui.requestRender());

      return {
        dispose: unsub,
        invalidate() {
          // Intentionally empty.
        },
        render(width: number): string[] {
          const footerLine = pipe(
            Effect.sync(() => ({
              branchEntries: ctx.sessionManager.getBranch(),
              branch: Option.fromNullable(footerData.getGitBranch()),
              statuses: footerData.getExtensionStatuses(),
              contextUsage: ctx.getContextUsage(),
              cwd: ctx.cwd,
              // biome-ignore lint/complexity/useLiteralKeys lint/correctness/noProcessGlobal: Node-only extension.
              home: Option.fromNullable(process.env["HOME"]),
              model: ctx.model as ModelInfo | undefined,
              thinkingLevel: pi.getThinkingLevel(),
              width,
              theme,
            })),
            Effect.map(buildFooterLine),
            Effect.runSync
          );

          return [footerLine];
        },
      };
    });
  });
};

export default footerExtension;
