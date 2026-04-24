import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.js";
import { agentHintForWarning } from "./hints.js";
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

export const __test = {
  getConfigSignature,
  getConfigOrBlockReason,
  resetConfigCache,
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

      if (isToolCallEventType("bash", event)) {
        const action = actionForCommand(event.input.command, configOrReason);
        if (!action) {
          return undefined;
        }
        if (action.type === "warn") {
          emitGuardrailWarning(pi, ctx, event.toolName, action.message);
          return undefined;
        }
        return { block: true, reason: action.message };
      }

      if (isToolCallEventType<"pwsh", { command?: string }>("pwsh", event)) {
        const command = typeof event.input.command === "string" ? event.input.command : "";
        const action = actionForCommand(command, configOrReason);
        if (!action) {
          return undefined;
        }
        if (action.type === "warn") {
          emitGuardrailWarning(pi, ctx, event.toolName, action.message);
          return undefined;
        }
        return { block: true, reason: action.message };
      }

      if (isToolCallEventType("read", event)) {
        const reason = reasonForPath(event.input.path, "read", configOrReason);
        return reason ? { block: true, reason } : undefined;
      }

      if (isToolCallEventType("write", event)) {
        const reason = reasonForPath(event.input.path, "write", configOrReason);
        return reason ? { block: true, reason } : undefined;
      }

      if (isToolCallEventType("edit", event)) {
        const reason = reasonForPath(event.input.path, "edit", configOrReason);
        return reason ? { block: true, reason } : undefined;
      }

      return undefined;
    });
  };
}

export default createGuardrails(configPath);
