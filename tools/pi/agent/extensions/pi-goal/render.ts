import type { Theme } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import {
  getReusableText,
  joinRenderSegments,
} from "../_shared/render-utils.js";
import type { GoalEventKind, GoalState } from "./format.js";
import { goalEventStatus, goalUsage } from "./format.js";
import { EVENT_TYPE } from "./state.js";

type GoalEventDetails = {
  kind?: GoalEventKind;
  goal?: GoalState | null;
};

type MessageLike = {
  details?: unknown;
};

type RendererOptions = {
  expanded?: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object";

const readDetails = (message: MessageLike): GoalEventDetails =>
  isRecord(message.details) ? (message.details as GoalEventDetails) : {};

export const previewObjective = (objective: string, maxChars = 90): string => {
  const compact = objective.replace(/\s+/g, " ").trim();
  const chars = [...compact];
  return chars.length <= maxChars
    ? compact
    : `${chars.slice(0, Math.max(0, maxChars - 1)).join("")}…`;
};

const goalEventIcon = (kind: GoalEventKind): string => {
  if (kind === "paused") return "‖";
  if (kind === "cleared") return "✕";
  if (kind === "complete") return "✓";
  return "⚑";
};

const objectivePreviewLine = (state: GoalState, theme: Theme): string =>
  `  ${theme.fg("muted", "↳")} ${theme.fg("muted", previewObjective(state.objective))}`;

const shouldShowSnapshotUsage = (kind: GoalEventKind): boolean =>
  kind === "paused" ||
  kind === "resumed" ||
  kind === "complete" ||
  kind === "cleared";

const buildCollapsedGoalEventText = (
  kind: GoalEventKind,
  state: GoalState | null,
  theme: Theme,
): string => {
  const segments = [
    `${theme.fg("muted", goalEventIcon(kind))} ${theme.fg("toolTitle", theme.bold("goal"))}`,
    theme.fg("muted", goalEventStatus(kind)),
  ];
  if (state && shouldShowSnapshotUsage(kind))
    segments.push(theme.fg("muted", goalUsage(state)));
  const header = joinRenderSegments(segments, theme);
  return state ? `${header}\n${objectivePreviewLine(state, theme)}` : header;
};

export const buildGoalEventText = (
  message: MessageLike,
  options: RendererOptions,
  theme: Theme,
): string => {
  const details = readDetails(message);
  const kind = details.kind ?? "continuation";
  const state = details.goal ?? null;
  const collapsed = buildCollapsedGoalEventText(kind, state, theme);

  if (!options.expanded || !state) return collapsed;

  return `${collapsed}\n  ${theme.fg("dim", "status:")} ${theme.fg("muted", state.status)}\n  ${theme.fg("dim", "objective:")} ${theme.fg("muted", state.objective)}`;
};

export const buildUpdateGoalCallText = (
  state: GoalState | null,
  theme: Theme,
): string => {
  const header = joinRenderSegments(
    [
      `${theme.fg("muted", "✓")} ${theme.fg("toolTitle", theme.bold("goal"))}`,
      theme.fg("muted", "complete"),
    ],
    theme,
  );
  return state ? `${header}\n${objectivePreviewLine(state, theme)}` : header;
};

export const buildUpdateGoalResultText = (
  rawText: string,
  isError: boolean,
  theme: Theme,
): string => {
  if (!isError) return "";
  return `  ${theme.fg("error", rawText || "update_goal failed")}`;
};

export type MessageRendererApi = {
  registerMessageRenderer: (
    customType: string,
    renderer: (
      message: MessageLike,
      options: RendererOptions,
      theme: Theme,
    ) => Text,
  ) => void;
};

export const registerGoalRenderer = (pi: MessageRendererApi): void => {
  pi.registerMessageRenderer(
    EVENT_TYPE,
    (message, options, theme) =>
      new Text(buildGoalEventText(message, options, theme), 0, 0),
  );
};

export const renderReusableText = (
  lastComponent: unknown,
  value: string,
): Text => {
  const text = getReusableText(lastComponent);
  text.setText(value);
  return text;
};
