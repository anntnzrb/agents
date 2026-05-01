import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.js";
import { agentHintForBlock, agentHintForWarning } from "./hints.js";
import { actionForCommand } from "./matcher.js";
import { reasonForPath } from "./paths.js";
import type { GuardrailsConfig } from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const configPath = join(__dirname, "guardrails.jsonc");

let cachedSignature: string | null = null;
let cachedConfigOrReason: GuardrailsConfig | string | undefined;
const emittedWarnings = new Set<string>();

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
        return { block: true, reason: agentHintForBlock(action.message) };
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
        return { block: true, reason: agentHintForBlock(action.message) };
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
