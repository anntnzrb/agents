import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.js";
import { reasonForCommand } from "./matcher.js";
import { reasonForPath } from "./paths.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const configPath = join(__dirname, "guardrails.jsonc");

const getConfigOrBlockReason = (path: string) => {
  const result = loadConfig(path);
  return result.ok ? result.config : result.reason;
};

export function createGuardrails(path: string) {
  return function guardrails(pi: ExtensionAPI): void {
    pi.on("tool_call", async (event) => {
      const configOrReason = getConfigOrBlockReason(path);
      if (typeof configOrReason === "string") {
        return { block: true, reason: configOrReason };
      }

      if (isToolCallEventType("bash", event)) {
        const reason = reasonForCommand(event.input.command, configOrReason);
        return reason ? { block: true, reason } : undefined;
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
