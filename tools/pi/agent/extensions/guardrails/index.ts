import type { ExtensionAPI, ExtensionContext, Skill } from "@earendil-works/pi-coding-agent";
import { getAgentDir, isToolCallEventType, loadSkills } from "@earendil-works/pi-coding-agent";
import { statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.js";
import { agentHintForBlock, agentHintForWarning } from "./hints.js";
import { actionForCommand } from "./matcher.js";
import { reasonForPath } from "./paths.js";
import type { BlockAction, GuardrailsConfig, SkillBinding } from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const configPath = join(__dirname, "guardrails.jsonc");

let cachedSignature: string | null = null;
let cachedConfigOrReason: GuardrailsConfig | string | undefined;
const emittedWarnings = new Set<string>();
const loadedSkills = new Set<string>();

const getConfigSignature = (path: string): string => {
  try {
    const stats = statSync(path);
    return `${path}:${stats.mtimeMs}:${stats.size}`;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return `${path}:missing:${message}`;
  }
};

const getConfigOrBlockReason = (path: string) => {
  const signature = getConfigSignature(path);
  if (cachedSignature === signature && cachedConfigOrReason !== undefined) {
    return cachedConfigOrReason;
  }

  const result = loadConfig(path);
  const configOrReason = result.ok ? result.config : result.reason;
  cachedSignature = signature;
  cachedConfigOrReason = configOrReason;
  return configOrReason;
};

const resetConfigCache = () => {
  cachedSignature = null;
  cachedConfigOrReason = undefined;
  emittedWarnings.clear();
  loadedSkills.clear();
};

const emitGuardrailWarning = (pi: ExtensionAPI, ctx: ExtensionContext, toolName: string, message: string) => {
  ctx.ui.notify(message, "warning");
  const key = `${toolName}:${message}`;
  if (emittedWarnings.has(key)) return;
  emittedWarnings.add(key);
  pi.sendMessage(
    {
      customType: "guardrails-warning",
      content: agentHintForWarning(message, pi.getAllTools()),
      display: false,
    },
    { triggerTurn: false },
  );
};

const findSkill = (ctx: ExtensionContext, skillName: string): Skill | undefined =>
  loadSkills({ cwd: ctx.cwd, agentDir: getAgentDir(), skillPaths: [], includeDefaults: true }).skills.find((skill) => skill.name === skillName);

const skillInjectionContent = (skill: Skill, content: string): string => `<required_skill_load name="${skill.name}" source="${skill.filePath}">
${content}
</required_skill_load>`;

type SkillLoadState =
  | { status: "not-required" }
  | { status: "already-loaded"; skillName: string }
  | { status: "loaded"; skillName: string }
  | { status: "missing"; skillName: string }
  | { status: "error"; skillName: string; detail: string };

const loadRequiredSkill = async (pi: ExtensionAPI, ctx: ExtensionContext, skillName: string | undefined): Promise<SkillLoadState> => {
  if (!skillName) return { status: "not-required" };
  if (loadedSkills.has(skillName)) return { status: "already-loaded", skillName };

  const skill = findSkill(ctx, skillName);
  if (!skill) {
    ctx.ui.notify(`Guardrails could not find required skill: ${skillName}`, "warning");
    return { status: "missing", skillName };
  }

  try {
    const content = await readFile(skill.filePath, "utf8");
    loadedSkills.add(skillName);
    pi.sendMessage(
      {
        customType: "guardrails-skill-load",
        content: skillInjectionContent(skill, content),
        display: false,
        details: { skill: skill.name, path: skill.filePath },
      },
      { deliverAs: "steer", triggerTurn: false },
    );
    ctx.ui.notify(`Guardrails loaded skill: ${skill.name}`, "info");
    return { status: "loaded", skillName };
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    ctx.ui.notify(`Guardrails could not load required skill ${skillName}: ${detail}`, "warning");
    return { status: "error", skillName, detail };
  }
};

type ToolEventLike = {
  toolName?: string;
  input?: Record<string, unknown>;
};

const toolNameOf = (event: unknown): string => {
  const toolName = (event as ToolEventLike).toolName;
  return typeof toolName === "string" ? toolName : "";
};

const isNamedTool = (event: unknown, name: string): event is ToolEventLike => {
  const toolName = toolNameOf(event);
  return toolName === name || toolName === `functions.${name}` || toolName.endsWith(`.${name}`);
};

const inputString = (event: unknown, key: string): string | null => {
  const input = (event as ToolEventLike).input;
  const value = input?.[key];
  return typeof value === "string" ? value : null;
};

const bindingForAction = (action: BlockAction, config: GuardrailsConfig): SkillBinding | null => {
  if (!action.requiresBinding) return null;
  return config.skillBindings[action.requiresBinding] ?? null;
};

const resolvedSkillName = (action: BlockAction, config: GuardrailsConfig): string | undefined =>
  bindingForAction(action, config)?.requiresSkill ?? action.requiresSkill;

const resolvedWorkflow = (action: BlockAction, config: GuardrailsConfig): string | undefined =>
  bindingForAction(action, config)?.requiredWorkflow ?? action.requiredWorkflow;

const hintInputForBlockAction = (action: BlockAction, config: GuardrailsConfig): { message: string; requiresSkill?: string; requiredWorkflow?: string } => {
  const out: { message: string; requiresSkill?: string; requiredWorkflow?: string } = { message: action.message };
  const skillName = resolvedSkillName(action, config);
  const workflow = resolvedWorkflow(action, config);
  if (skillName) out.requiresSkill = skillName;
  if (workflow) out.requiredWorkflow = workflow;
  return out;
};

export const __test = {
  getConfigSignature,
  getConfigOrBlockReason,
  resetConfigCache,
  agentHintForBlock,
  agentHintForWarning,
  emitGuardrailWarning,
};

export function createGuardrails(path: string) {
  return function guardrails(pi: ExtensionAPI): void {
    pi.on("session_start", () => {
      loadedSkills.clear();
    });

    pi.on("tool_call", async (event, ctx) => {
      const configOrReason = getConfigOrBlockReason(path);
      if (typeof configOrReason === "string") {
        return { block: true, reason: configOrReason };
      }

      if (isToolCallEventType("bash", event) || isNamedTool(event, "bash")) {
        const command = inputString(event, "command") ?? "";
        const action = actionForCommand(command, configOrReason);
        if (!action) {
          return undefined;
        }
        if (action.type === "warn") {
          emitGuardrailWarning(pi, ctx, toolNameOf(event), action.message);
          return undefined;
        }

        const skillLoadState = await loadRequiredSkill(pi, ctx, resolvedSkillName(action, configOrReason));
        if (skillLoadState.status === "missing") {
          return {
            block: true,
            reason: `Guardrail blocked this command and could not load required skill \`${skillLoadState.skillName}\`. Ensure the skill exists and try again.`,
          };
        }
        if (skillLoadState.status === "error") {
          return {
            block: true,
            reason: `Guardrail blocked this command and failed to load required skill \`${skillLoadState.skillName}\`: ${skillLoadState.detail}`,
          };
        }

        return {
          block: true,
          reason: agentHintForBlock(hintInputForBlockAction(action, configOrReason)),
        };
      }

      if (isToolCallEventType<"pwsh", { command?: string }>("pwsh", event) || isNamedTool(event, "pwsh")) {
        const command = inputString(event, "command") ?? "";
        const action = actionForCommand(command, configOrReason);
        if (!action) {
          return undefined;
        }
        if (action.type === "warn") {
          emitGuardrailWarning(pi, ctx, toolNameOf(event), action.message);
          return undefined;
        }

        const skillLoadState = await loadRequiredSkill(pi, ctx, resolvedSkillName(action, configOrReason));
        if (skillLoadState.status === "missing") {
          return {
            block: true,
            reason: `Guardrail blocked this command and could not load required skill \`${skillLoadState.skillName}\`. Ensure the skill exists and try again.`,
          };
        }
        if (skillLoadState.status === "error") {
          return {
            block: true,
            reason: `Guardrail blocked this command and failed to load required skill \`${skillLoadState.skillName}\`: ${skillLoadState.detail}`,
          };
        }

        return {
          block: true,
          reason: agentHintForBlock(hintInputForBlockAction(action, configOrReason)),
        };
      }

      if (isToolCallEventType("read", event) || isNamedTool(event, "read")) {
        const path = inputString(event, "path") ?? "";
        const reason = reasonForPath(path, "read", configOrReason);
        return reason ? { block: true, reason } : undefined;
      }

      if (isToolCallEventType("write", event) || isNamedTool(event, "write")) {
        const path = inputString(event, "path") ?? "";
        const reason = reasonForPath(path, "write", configOrReason);
        return reason ? { block: true, reason } : undefined;
      }

      if (isToolCallEventType("edit", event) || isNamedTool(event, "edit")) {
        const path = inputString(event, "path") ?? "";
        const reason = reasonForPath(path, "edit", configOrReason);
        return reason ? { block: true, reason } : undefined;
      }

      return undefined;
    });
  };
}

export default createGuardrails(configPath);
