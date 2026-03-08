import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  CUSTOM_MODE_NAME,
  DEFAULT_MODE_ORDER,
  getCustomOverlay,
  getLastObservedModel,
  getRequestEditorRender,
  runtime,
  setCustomOverlay,
} from "./modes-state.ts";
import type { ModeName, ModeSpec, ModesFile } from "./modes-state.ts";
import type { ModelSelectEvent, ThinkingLevel } from "./types.ts";

function expandUserPath(filePath: string): string {
  if (filePath === "~") return os.homedir();
  if (filePath.startsWith("~/")) return path.join(os.homedir(), filePath.slice(2));
  return filePath;
}

function getGlobalAgentDir(): string {
  const env = process.env.PI_CODING_AGENT_DIR;
  if (env) return expandUserPath(env);
  return path.join(os.homedir(), ".pi", "agent");
}

function getGlobalModesPath(): string {
  return path.join(getGlobalAgentDir(), "modes.json");
}

function getProjectModesPath(cwd: string): string {
  return path.join(cwd, ".pi", "modes.json");
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fs.stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function ensureDirForFile(filePath: string): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
}

async function getMtimeMs(filePath: string): Promise<number | null> {
  try {
    const stats = await fs.stat(filePath);
    return stats.mtimeMs;
  } catch {
    return null;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getLockPathForFile(filePath: string): string {
  return `${filePath}.lock`;
}

async function withFileLock<T>(filePath: string, fn: () => Promise<T>): Promise<T> {
  const lockPath = getLockPathForFile(filePath);
  await ensureDirForFile(lockPath);

  const start = Date.now();
  while (true) {
    try {
      const handle = await fs.open(lockPath, "wx");
      try {
        await handle.writeFile(
          JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }) + "\n",
          "utf8"
        );
      } catch {
        // ignore
      }

      try {
        return await fn();
      } finally {
        await handle.close().catch(() => {});
        await fs.unlink(lockPath).catch(() => {});
      }
    } catch (error: unknown) {
      if (!isErrorCode(error, "EEXIST")) throw error;

      try {
        const stats = await fs.stat(lockPath);
        if (Date.now() - stats.mtimeMs > 30_000) {
          await fs.unlink(lockPath);
          continue;
        }
      } catch {
        // ignore
      }

      if (Date.now() - start > 5_000) {
        throw new Error(`Timed out waiting for lock: ${lockPath}`);
      }
      await sleep(40 + Math.random() * 80);
    }
  }
}

function isErrorCode(error: unknown, code: string): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === code);
}

async function atomicWriteUtf8(filePath: string, content: string): Promise<void> {
  await ensureDirForFile(filePath);

  const dir = path.dirname(filePath);
  const base = path.basename(filePath);
  const tmpPath = path.join(dir, `.${base}.tmp.${process.pid}.${Math.random().toString(16).slice(2)}`);

  await fs.writeFile(tmpPath, content, "utf8");

  try {
    await fs.rename(tmpPath, filePath);
  } catch (error: unknown) {
    if (isErrorCode(error, "EEXIST") || isErrorCode(error, "EPERM")) {
      await fs.unlink(filePath).catch(() => {});
      await fs.rename(tmpPath, filePath);
    } else {
      await fs.unlink(tmpPath).catch(() => {});
      throw error;
    }
  }
}

function cloneModesFile(file: ModesFile): ModesFile {
  return JSON.parse(JSON.stringify(file)) as ModesFile;
}

type ModeSpecPatch = {
  provider?: string | null;
  modelId?: string | null;
  thinkingLevel?: ThinkingLevel | null;
  color?: string | null;
};

type ModesPatch = {
  currentMode?: ModeName;
  modes?: Record<ModeName, ModeSpecPatch | null>;
};

function computeModesPatch(
  base: ModesFile,
  next: ModesFile,
  includeCurrentMode: boolean
): ModesPatch | null {
  const patch: ModesPatch = {};

  if (includeCurrentMode && base.currentMode !== next.currentMode) {
    patch.currentMode = next.currentMode;
  }

  const keys = new Set([...Object.keys(base.modes), ...Object.keys(next.modes)]);
  const modesPatch: Record<ModeName, ModeSpecPatch | null> = {};

  for (const key of keys) {
    const previous = base.modes[key];
    const current = next.modes[key];

    if (!current) {
      if (previous) modesPatch[key] = null;
      continue;
    }
    if (!previous) {
      modesPatch[key] = { ...current };
      continue;
    }

    const diff: ModeSpecPatch = {};
    const fields: Array<keyof ModeSpec> = ["provider", "modelId", "thinkingLevel", "color"];
    for (const field of fields) {
      const previousValue = previous[field];
      const currentValue = current[field];
      if (previousValue !== currentValue) {
        (diff as Record<keyof ModeSpec, ModeSpecPatch[keyof ModeSpecPatch]>)[field] = currentValue ?? null;
      }
    }
    if (Object.keys(diff).length > 0) {
      modesPatch[key] = diff;
    }
  }

  if (Object.keys(modesPatch).length > 0) {
    patch.modes = modesPatch;
  }

  if (!patch.modes && patch.currentMode === undefined) return null;
  return patch;
}

function applyModesPatch(target: ModesFile, patch: ModesPatch): void {
  if (patch.currentMode !== undefined) {
    target.currentMode = patch.currentMode;
  }

  if (!patch.modes) return;
  for (const [mode, specPatch] of Object.entries(patch.modes)) {
    if (specPatch === null) {
      delete target.modes[mode];
      continue;
    }

    const targetSpec: Record<string, unknown> = ((target.modes[mode] ??= {}) as Record<
      string,
      unknown
    >) ?? {};
    for (const [key, value] of Object.entries(specPatch)) {
      if (value === null || value === undefined) {
        delete targetSpec[key];
      } else {
        targetSpec[key] = value;
      }
    }
  }
}

function normalizeThinkingLevel(level: unknown): ThinkingLevel | undefined {
  if (typeof level !== "string") return undefined;
  const value = level as ThinkingLevel;
  const allowed: ThinkingLevel[] = ["off", "minimal", "low", "medium", "high", "xhigh"];
  return allowed.includes(value) ? value : undefined;
}

function sanitizeModeSpec(spec: unknown): ModeSpec {
  const obj = (spec && typeof spec === "object" ? spec : {}) as Record<string, unknown>;
  return {
    provider: typeof obj.provider === "string" ? obj.provider : undefined,
    modelId: typeof obj.modelId === "string" ? obj.modelId : undefined,
    thinkingLevel: normalizeThinkingLevel(obj.thinkingLevel),
    color: typeof obj.color === "string" ? obj.color : undefined,
  };
}

function createDefaultModes(ctx: ExtensionContext, pi: ExtensionAPI): ModesFile {
  const currentModel = ctx.model;
  const currentThinking = pi.getThinkingLevel();

  const base: ModeSpec = {
    provider: currentModel?.provider,
    modelId: currentModel?.id,
    thinkingLevel: currentThinking,
  };

  return {
    version: 1,
    currentMode: "default",
    modes: {
      default: { ...base },
      fast: { ...base, thinkingLevel: "off" },
    },
  };
}

function ensureDefaultModeEntries(file: ModesFile, ctx: ExtensionContext, pi: ExtensionAPI): void {
  for (const name of DEFAULT_MODE_ORDER) {
    if (!file.modes[name]) {
      const defaults = createDefaultModes(ctx, pi);
      const fallback = defaults.modes[name];
      if (fallback) file.modes[name] = fallback;
    }
  }

  if (file.currentMode === CUSTOM_MODE_NAME) {
    file.currentMode = "" as ModeName;
  }

  if (!file.currentMode || !(file.currentMode in file.modes) || file.currentMode === CUSTOM_MODE_NAME) {
    const first = Object.keys(file.modes).find((key) => key !== CUSTOM_MODE_NAME);
    file.currentMode = file.modes.default ? "default" : (first ?? "default");
  }
}

async function loadModesFile(
  filePath: string,
  ctx: ExtensionContext,
  pi: ExtensionAPI
): Promise<ModesFile> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const currentMode = typeof parsed.currentMode === "string" ? parsed.currentMode : "default";
    const modesRaw =
      parsed.modes && typeof parsed.modes === "object"
        ? (parsed.modes as Record<string, unknown>)
        : {};
    const modes: Record<string, ModeSpec> = {};
    for (const [key, value] of Object.entries(modesRaw)) {
      modes[key] = sanitizeModeSpec(value);
    }
    const file: ModesFile = { version: 1, currentMode, modes };
    ensureDefaultModeEntries(file, ctx, pi);
    return file;
  } catch {
    return createDefaultModes(ctx, pi);
  }
}

async function saveModesFile(filePath: string, data: ModesFile): Promise<void> {
  await atomicWriteUtf8(filePath, JSON.stringify(data, null, 2) + "\n");
}

export function orderedModeNames(modes: Record<string, ModeSpec>): string[] {
  return Object.keys(modes).filter((name) => name !== CUSTOM_MODE_NAME);
}

export function getModeBorderColor(
  ctx: ExtensionContext,
  pi: ExtensionAPI,
  mode: string
): (text: string) => string {
  const theme = ctx.ui.theme;
  const spec = runtime.data.modes[mode];

  if (spec?.color) {
    try {
      theme.getFgAnsi(spec.color as never);
      return (text: string) => theme.fg(spec.color as never, text);
    } catch {
      // fall through
    }
  }

  return theme.getThinkingBorderColor(pi.getThinkingLevel());
}

async function resolveModesPath(cwd: string): Promise<string> {
  const projectPath = getProjectModesPath(cwd);
  if (await fileExists(projectPath)) return projectPath;
  return getGlobalModesPath();
}

export function inferModeFromSelection(
  ctx: ExtensionContext,
  pi: ExtensionAPI,
  data: ModesFile
): string | null {
  const provider = ctx.model?.provider;
  const modelId = ctx.model?.id;
  const thinkingLevel = pi.getThinkingLevel();
  if (!provider || !modelId) return null;

  const names = orderedModeNames(data.modes);
  const supportsThinking = Boolean(ctx.model?.reasoning);

  if (supportsThinking) {
    for (const name of names) {
      const spec = data.modes[name];
      if (!spec) continue;
      if (spec.provider !== provider || spec.modelId !== modelId) continue;
      if ((spec.thinkingLevel ?? undefined) !== thinkingLevel) continue;
      return name;
    }
    return null;
  }

  const candidates: string[] = [];
  for (const name of names) {
    const spec = data.modes[name];
    if (!spec) continue;
    if (spec.provider !== provider || spec.modelId !== modelId) continue;
    candidates.push(name);
  }
  if (candidates.length === 0) return null;

  for (const name of candidates) {
    const spec = data.modes[name];
    if (!spec) continue;
    if ((spec.thinkingLevel ?? "off") === thinkingLevel) return name;
  }

  for (const name of candidates) {
    const spec = data.modes[name];
    if (!spec) continue;
    if (!spec.thinkingLevel) return name;
  }

  return candidates[0] ?? null;
}

export async function ensureRuntime(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
  const filePath = await resolveModesPath(ctx.cwd);

  const mtimeMs = await getMtimeMs(filePath);
  const filePathChanged = runtime.filePath !== filePath;
  const fileChanged = filePathChanged || runtime.fileMtimeMs !== mtimeMs;

  if (fileChanged) {
    runtime.filePath = filePath;
    runtime.fileMtimeMs = mtimeMs;

    const loaded = await loadModesFile(filePath, ctx, pi);
    ensureDefaultModeEntries(loaded, ctx, pi);
    runtime.data = loaded;
    runtime.baseline = cloneModesFile(runtime.data);

    if (filePathChanged && runtime.currentMode !== CUSTOM_MODE_NAME) {
      runtime.currentMode = runtime.data.currentMode;
      runtime.lastRealMode = runtime.currentMode;
    }
  }

  if (runtime.currentMode !== CUSTOM_MODE_NAME) {
    if (!runtime.currentMode || !(runtime.currentMode in runtime.data.modes)) {
      runtime.currentMode = runtime.data.currentMode;
    }
    if (!runtime.lastRealMode || !(runtime.lastRealMode in runtime.data.modes)) {
      runtime.lastRealMode = runtime.currentMode;
    }
  }
}

export async function persistRuntime(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
  if (!runtime.filePath) return;

  runtime.baseline ??= cloneModesFile(runtime.data);
  const patch = computeModesPatch(runtime.baseline, runtime.data, false);
  if (!patch) return;

  await withFileLock(runtime.filePath, async () => {
    const latest = await loadModesFile(runtime.filePath, ctx, pi);
    applyModesPatch(latest, patch);
    ensureDefaultModeEntries(latest, ctx, pi);
    await saveModesFile(runtime.filePath, latest);

    runtime.data = latest;
    runtime.baseline = cloneModesFile(latest);
    runtime.fileMtimeMs = await getMtimeMs(runtime.filePath);
  });
}

export function getCurrentSelectionSpec(pi: ExtensionAPI): ModeSpec {
  const currentModel = getLastObservedModel();
  return {
    provider: currentModel.provider,
    modelId: currentModel.modelId,
    thinkingLevel: pi.getThinkingLevel(),
  };
}

export async function storeSelectionIntoMode(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  mode: string,
  selection: ModeSpec
): Promise<void> {
  if (mode === CUSTOM_MODE_NAME) return;

  await ensureRuntime(pi, ctx);

  const existingTarget = runtime.data.modes[mode] ?? {};
  const next: ModeSpec = { ...existingTarget };

  if (selection.provider && selection.modelId) {
    next.provider = selection.provider;
    next.modelId = selection.modelId;
  }
  if (selection.thinkingLevel) next.thinkingLevel = selection.thinkingLevel;

  runtime.data.modes[mode] = next;
  await persistRuntime(pi, ctx);
}

export async function applyMode(pi: ExtensionAPI, ctx: ExtensionContext, mode: string): Promise<void> {
  await ensureRuntime(pi, ctx);

  if (mode === CUSTOM_MODE_NAME) {
    runtime.currentMode = CUSTOM_MODE_NAME;
    setCustomOverlay(getCurrentSelectionSpec(pi));
    getRequestEditorRender()?.();
    return;
  }

  const spec = runtime.data.modes[mode];
  if (!spec) {
    if (ctx.hasUI) {
      ctx.ui.notify(`Unknown mode: ${mode}`, "warning");
    }
    return;
  }

  runtime.currentMode = mode;
  runtime.lastRealMode = mode;
  setCustomOverlay(null);

  runtime.applying = true;
  let modelAppliedOk = true;
  try {
    if (spec.provider && spec.modelId) {
      const model = ctx.modelRegistry.find(spec.provider, spec.modelId);
      if (model) {
        const ok = await pi.setModel(model);
        modelAppliedOk = ok;
        if (!ok && ctx.hasUI) {
          ctx.ui.notify(`No API key available for ${spec.provider}/${spec.modelId}`, "warning");
        }
      } else {
        modelAppliedOk = false;
        if (ctx.hasUI) {
          ctx.ui.notify(
            `Mode "${mode}" references unknown model ${spec.provider}/${spec.modelId}`,
            "warning"
          );
        }
      }
    }

    if (spec.thinkingLevel) {
      pi.setThinkingLevel(spec.thinkingLevel);
    }
  } finally {
    runtime.applying = false;
  }

  if (!modelAppliedOk) {
    runtime.currentMode = CUSTOM_MODE_NAME;
    setCustomOverlay(getCurrentSelectionSpec(pi));
  }

  if (ctx.hasUI) {
    getRequestEditorRender()?.();
  }
}

export function getCurrentMode(): string {
  return runtime.currentMode;
}

export async function restoreModeFromSelection(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
  await ensureRuntime(pi, ctx);
  setCustomOverlay(null);

  const inferred = inferModeFromSelection(ctx, pi, runtime.data);
  if (inferred) {
    runtime.currentMode = inferred;
    runtime.lastRealMode = inferred;
    return;
  }

  runtime.currentMode = CUSTOM_MODE_NAME;
  setCustomOverlay(getCurrentSelectionSpec(pi));
}

export async function handleModelSelect(
  pi: ExtensionAPI,
  event: ModelSelectEvent,
  ctx: ExtensionContext
): Promise<void> {
  if (runtime.applying) return;

  await ensureRuntime(pi, ctx);
  if (runtime.currentMode !== CUSTOM_MODE_NAME) {
    runtime.lastRealMode = runtime.currentMode;
  }
  runtime.currentMode = CUSTOM_MODE_NAME;
  setCustomOverlay({
    provider: event.model.provider,
    modelId: event.model.id,
    thinkingLevel: pi.getThinkingLevel(),
  });

  if (ctx.hasUI) {
    getRequestEditorRender()?.();
  }
}

export function getCurrentOverlaySelection(pi: ExtensionAPI): ModeSpec {
  return getCustomOverlay() ?? getCurrentSelectionSpec(pi);
}
