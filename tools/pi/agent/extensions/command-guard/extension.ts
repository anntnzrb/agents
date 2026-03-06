import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

import { loadConfig } from "./config";
import { reasonForCommand } from "./matcher";

export function createCommandGuard(configPath: string) {
  return function commandGuard(pi: ExtensionAPI): void {
    pi.on("tool_call", async (event) => {
      if (!isToolCallEventType("bash", event)) {
        return;
      }

      const result = loadConfig(configPath);
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
