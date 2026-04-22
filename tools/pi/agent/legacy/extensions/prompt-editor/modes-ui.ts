import { ModelSelectorComponent, SettingsManager } from "@mariozechner/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

import {
  ALL_THINKING_LEVELS,
  CUSTOM_MODE_NAME,
  MODE_UI_ADD,
  MODE_UI_BACK,
  MODE_UI_CONFIGURE,
  runtime,
  THINKING_UNSET_LABEL,
} from "./modes-state.ts";
import type { ModeSpec } from "./modes-state.ts";
import {
  applyMode,
  ensureRuntime,
  getCurrentOverlaySelection,
  orderedModeNames,
  persistRuntime,
  storeSelectionIntoMode,
} from "./modes-core.ts";
import { getRequestEditorRender, setCustomOverlay } from "./modes-state.ts";
import type { ThinkingLevel } from "./types.ts";

function isDefaultModeName(name: string): boolean {
  return name === "default";
}

function isReservedModeName(name: string): boolean {
  return (
    name === CUSTOM_MODE_NAME ||
    name === MODE_UI_CONFIGURE ||
    name === MODE_UI_ADD ||
    name === MODE_UI_BACK
  );
}

function normalizeModeNameInput(name: string | undefined): string {
  return (name ?? "").trim();
}

function validateModeNameOrError(
  name: string,
  existing: Record<string, ModeSpec>,
  opts?: { allowExisting?: boolean }
): string | null {
  if (!name) return "Mode name cannot be empty";
  if (/\s/.test(name)) return "Mode name cannot contain whitespace";
  if (isReservedModeName(name)) return `Mode name \"${name}\" is reserved`;
  if (!opts?.allowExisting && existing[name]) return `Mode \"${name}\" already exists`;
  return null;
}

async function handleModeChoiceUI(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  choice: string
): Promise<void> {
  if (runtime.currentMode === CUSTOM_MODE_NAME && choice !== CUSTOM_MODE_NAME) {
    const action = await ctx.ui.select(`Mode \"${choice}\"`, ["use", "store"]);
    if (!action) return;

    if (action === "use") {
      await applyMode(pi, ctx, choice);
      return;
    }

    const overlay = getCurrentOverlaySelection(pi);
    await storeSelectionIntoMode(pi, ctx, choice, overlay);
    await applyMode(pi, ctx, choice);
    ctx.ui.notify(`Stored ${CUSTOM_MODE_NAME} into \"${choice}\"`, "info");
    return;
  }

  await applyMode(pi, ctx, choice);
}

export async function selectModeUI(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
  if (!ctx.hasUI) return;

  while (true) {
    await ensureRuntime(pi, ctx);
    const names = orderedModeNames(runtime.data.modes);
    const choice = await ctx.ui.select(
      `Mode (current: ${runtime.currentMode})`,
      [...names, MODE_UI_CONFIGURE]
    );
    if (!choice) return;

    if (choice === MODE_UI_CONFIGURE) {
      await configureModesUI(pi, ctx);
      continue;
    }

    await handleModeChoiceUI(pi, ctx, choice);
    return;
  }
}

async function configureModesUI(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
  if (!ctx.hasUI) return;

  while (true) {
    await ensureRuntime(pi, ctx);
    const names = orderedModeNames(runtime.data.modes);
    const choice = await ctx.ui.select("Configure modes", [...names, MODE_UI_ADD, MODE_UI_BACK]);
    if (!choice || choice === MODE_UI_BACK) return;

    if (choice === MODE_UI_ADD) {
      const created = await addModeUI(pi, ctx);
      if (created) {
        await editModeUI(pi, ctx, created);
      }
      continue;
    }

    await editModeUI(pi, ctx, choice);
  }
}

async function addModeUI(pi: ExtensionAPI, ctx: ExtensionContext): Promise<string | undefined> {
  if (!ctx.hasUI) return undefined;
  await ensureRuntime(pi, ctx);

  while (true) {
    const raw = await ctx.ui.input("New mode name", "e.g. docs, review, planning");
    if (raw === undefined) return undefined;

    const name = normalizeModeNameInput(raw);
    const error = validateModeNameOrError(name, runtime.data.modes);
    if (error) {
      ctx.ui.notify(error, "warning");
      continue;
    }

    const selection = getCurrentOverlaySelection(pi);
    runtime.data.modes[name] = {
      provider: selection.provider,
      modelId: selection.modelId,
      thinkingLevel: selection.thinkingLevel,
    };
    await persistRuntime(pi, ctx);
    ctx.ui.notify(`Added mode \"${name}\"`, "info");
    return name;
  }
}

async function editModeUI(pi: ExtensionAPI, ctx: ExtensionContext, mode: string): Promise<void> {
  if (!ctx.hasUI) return;

  let modeName = mode;

  while (true) {
    await ensureRuntime(pi, ctx);
    const spec = runtime.data.modes[modeName];
    if (!spec) return;

    const modelLabel = spec.provider && spec.modelId ? `${spec.provider}/${spec.modelId}` : "(no model)";
    const thinkingLabel = spec.thinkingLevel ?? THINKING_UNSET_LABEL;

    const actions = ["Change name", "Change model", "Change thinking level"];
    if (!isDefaultModeName(modeName)) actions.push("Delete mode");
    actions.push(MODE_UI_BACK);

    const action = await ctx.ui.select(
      `Edit mode \"${modeName}\"  model: ${modelLabel}  thinking: ${thinkingLabel}`,
      actions
    );
    if (!action || action === MODE_UI_BACK) return;

    if (action === "Change name") {
      const renamed = await renameModeUI(pi, ctx, modeName);
      if (renamed) modeName = renamed;
      continue;
    }

    if (action === "Change model") {
      const selected = await pickModelForModeUI(ctx, spec);
      if (!selected) continue;
      spec.provider = selected.provider;
      spec.modelId = selected.modelId;
      runtime.data.modes[modeName] = spec;
      await persistRuntime(pi, ctx);
      ctx.ui.notify(`Updated model for \"${modeName}\"`, "info");

      if (runtime.currentMode === modeName) {
        await applyMode(pi, ctx, modeName);
      }
      continue;
    }

    if (action === "Change thinking level") {
      const level = await pickThinkingLevelForModeUI(ctx, spec.thinkingLevel);
      if (level === undefined) continue;

      if (level === null) delete spec.thinkingLevel;
      else spec.thinkingLevel = level;

      runtime.data.modes[modeName] = spec;
      await persistRuntime(pi, ctx);
      ctx.ui.notify(`Updated thinking level for \"${modeName}\"`, "info");

      if (runtime.currentMode === modeName) {
        await applyMode(pi, ctx, modeName);
      }
      continue;
    }

    if (action === "Delete mode") {
      const ok = await ctx.ui.confirm("Delete mode", `Delete mode \"${modeName}\"?`);
      if (!ok) continue;

      delete runtime.data.modes[modeName];
      await persistRuntime(pi, ctx);

      if (runtime.currentMode === modeName) {
        runtime.currentMode = CUSTOM_MODE_NAME;
        setCustomOverlay(getCurrentOverlaySelection(pi));
      }
      if (runtime.lastRealMode === modeName) {
        runtime.lastRealMode = "default";
      }
      getRequestEditorRender()?.();
      ctx.ui.notify(`Deleted mode \"${modeName}\"`, "info");
      return;
    }
  }
}

function renameModesRecord(
  modes: Record<string, ModeSpec>,
  oldName: string,
  newName: string
): Record<string, ModeSpec> {
  const next: Record<string, ModeSpec> = {};
  for (const [key, value] of Object.entries(modes)) {
    next[key === oldName ? newName : key] = value;
  }
  return next;
}

async function renameModeUI(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  oldName: string
): Promise<string | undefined> {
  if (!ctx.hasUI) return undefined;

  if (isDefaultModeName(oldName)) {
    ctx.ui.notify(`Cannot rename default mode \"${oldName}\"`, "warning");
    return oldName;
  }

  await ensureRuntime(pi, ctx);

  while (true) {
    const raw = await ctx.ui.input(`Rename mode \"${oldName}\"`, oldName);
    if (raw === undefined) return undefined;

    const newName = normalizeModeNameInput(raw);
    if (!newName || newName === oldName) return oldName;

    const error = validateModeNameOrError(newName, runtime.data.modes);
    if (error) {
      ctx.ui.notify(error, "warning");
      continue;
    }

    runtime.data.modes = renameModesRecord(runtime.data.modes, oldName, newName);
    await persistRuntime(pi, ctx);

    if (runtime.currentMode === oldName) runtime.currentMode = newName;
    if (runtime.lastRealMode === oldName) runtime.lastRealMode = newName;
    getRequestEditorRender()?.();

    ctx.ui.notify(`Renamed \"${oldName}\" → \"${newName}\"`, "info");
    return newName;
  }
}

async function pickModelForModeUI(
  ctx: ExtensionContext,
  spec: ModeSpec
): Promise<{ provider: string; modelId: string } | undefined> {
  if (!ctx.hasUI) return undefined;

  const settingsManager = SettingsManager.inMemory();
  const currentModel =
    spec.provider && spec.modelId ? ctx.modelRegistry.find(spec.provider, spec.modelId) : ctx.model;
  const scopedModels: Array<{ model: unknown; thinkingLevel: string }> = [];

  return ctx.ui.custom<{ provider: string; modelId: string } | undefined>(
    (tui, _theme, _keybindings, done) => {
      const selector = new ModelSelectorComponent(
        tui,
        currentModel,
        settingsManager,
        ctx.modelRegistry as never,
        scopedModels as never,
        (model) => done({ provider: model.provider, modelId: model.id }),
        () => done(undefined)
      );
      return selector;
    }
  );
}

async function pickThinkingLevelForModeUI(
  ctx: ExtensionContext,
  current: ThinkingLevel | undefined
): Promise<ThinkingLevel | null | undefined> {
  if (!ctx.hasUI) return undefined;

  const defaultValue = current ?? "off";
  const options = [...ALL_THINKING_LEVELS, THINKING_UNSET_LABEL];
  const ordered = [defaultValue, ...options.filter((value) => value !== defaultValue)];

  const choice = await ctx.ui.select("Thinking level", ordered);
  if (!choice) return undefined;
  if (choice === THINKING_UNSET_LABEL) return null;
  if (ALL_THINKING_LEVELS.includes(choice as ThinkingLevel)) return choice as ThinkingLevel;
  return undefined;
}

export async function cycleMode(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
  if (!ctx.hasUI) return;
  await ensureRuntime(pi, ctx);
  const names = orderedModeNames(runtime.data.modes);
  if (names.length === 0) return;

  const baseMode = runtime.currentMode === CUSTOM_MODE_NAME ? runtime.lastRealMode : runtime.currentMode;
  const idx = Math.max(0, names.indexOf(baseMode));
  const next = names[(idx + 1 + names.length) % names.length] ?? names[0];
  if (!next) return;
  await applyMode(pi, ctx, next);
}

export async function handleModeCommand(
  pi: ExtensionAPI,
  args: string,
  ctx: ExtensionContext
): Promise<void> {
  const tokens = args
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);

  if (tokens.length === 0) {
    await selectModeUI(pi, ctx);
    return;
  }

  if (tokens[0] === "store") {
    await ensureRuntime(pi, ctx);

    let target = tokens[1];
    if (!target) {
      if (!ctx.hasUI) return;
      const names = orderedModeNames(runtime.data.modes);
      target = await ctx.ui.select("Store current selection into mode", names);
      if (!target) return;
    }

    if (target === CUSTOM_MODE_NAME) {
      if (ctx.hasUI) ctx.ui.notify(`Cannot store into \"${CUSTOM_MODE_NAME}\"`, "warning");
      return;
    }

    const selection = getCurrentOverlaySelection(pi);
    await storeSelectionIntoMode(pi, ctx, target, selection);
    if (ctx.hasUI) ctx.ui.notify(`Stored current selection into \"${target}\"`, "info");
    return;
  }

  const mode = tokens[0];
  if (!mode) return;
  await applyMode(pi, ctx, mode);
}
