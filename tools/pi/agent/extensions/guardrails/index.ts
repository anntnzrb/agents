import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config";
import { reasonForCommand } from "./matcher";

const __dirname = dirname(fileURLToPath(import.meta.url));
const configPath = join(__dirname, "guardrails.jsonc");

export function createGuardrails(path: string) {
  return function guardrails(pi: ExtensionAPI): void {
    pi.on("tool_call", async (event) => {
      if (!isToolCallEventType("bash", event)) {
        return;
      }

      const result = loadConfig(path);
      if (!result.ok) {
        return { block: true, reason: result.reason };
      }

      const reason = reasonForCommand(event.input.command, result.config);
      if (!reason) {
        return;
      }

      return { block: true, reason };
    });
  };
}

export default createGuardrails(configPath);
