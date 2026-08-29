import type { ThinkingLevel } from "./types.js";

export type ModeName = string;

export type ModeSpec = {
  provider?: string | undefined;
  modelId?: string | undefined;
  thinkingLevel?: ThinkingLevel | undefined;
  /**
   * Optional theme color token to use for the editor border.
   * If unset, the border color is derived from the current thinking level.
   */
  color?: string | undefined;
};

export type ModesFile = {
  version: 1;
  currentMode: ModeName;
  modes: Record<ModeName, ModeSpec>;
};

export type ModeRuntime = {
  filePath: string;
  fileMtimeMs: number | null;
  baseline: ModesFile | null;
  data: ModesFile;
  lastRealMode: string;
  currentMode: string;
  applying: boolean;
};

export const DEFAULT_MODE_ORDER = ["default"] as const;
export const CUSTOM_MODE_NAME = "custom" as const;

export const MODE_UI_CONFIGURE = "Configure modes…";
export const MODE_UI_ADD = "Add mode…";
export const MODE_UI_BACK = "Back";

export const ALL_THINKING_LEVELS: ThinkingLevel[] = [
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
];
export const THINKING_UNSET_LABEL = "(don't change)";

export const runtime: ModeRuntime = {
  filePath: "",
  fileMtimeMs: null,
  baseline: null,
  data: { version: 1, currentMode: "default", modes: {} },
  lastRealMode: "default",
  currentMode: "default",
  applying: false,
};

let requestEditorRender: (() => void) | undefined;
let customOverlay: ModeSpec | null = null;
let lastObservedModel: { provider?: string | undefined; modelId?: string | undefined } = {};

export function getRequestEditorRender(): (() => void) | undefined {
  return requestEditorRender;
}

export function setRequestEditorRender(
  callback: (() => void) | undefined,
): void {
  requestEditorRender = callback;
}

export function getCustomOverlay(): ModeSpec | null {
  return customOverlay;
}

export function setCustomOverlay(overlay: ModeSpec | null): void {
  customOverlay = overlay;
}

export function setLastObservedModel(
  provider?: string,
  modelId?: string,
): void {
  lastObservedModel = { provider, modelId };
}

export function getLastObservedModel(): {
  provider?: string | undefined;
  modelId?: string | undefined;
} {
  return lastObservedModel;
}
