import type { Plugin } from "@opencode-ai/plugin";

const RTK_SYSTEM_GUIDANCE =
  "RTK automatically filters supported shell commands. Prefer native structured tools, use raw commands for exact or machine-readable output, and rerun raw when filtered output hides diagnostic evidence.";

export const RtkOpenCodePlugin: Plugin = async ({ $ }) => {
  try {
    await $`which rtk`.quiet();
  } catch {
    console.warn("[rtk] rtk binary not found in PATH - plugin disabled");
    return {};
  }

  return {
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(RTK_SYSTEM_GUIDANCE);
    },
    "tool.execute.before": async (input, output) => {
      const tool = String(input?.tool ?? "").toLowerCase();
      if (tool !== "bash" && tool !== "shell") return;

      const args = output?.args;
      if (!args || typeof args !== "object") return;

      const command = (args as Record<string, unknown>).command;
      if (typeof command !== "string" || !command) return;

      try {
        const result = await $`rtk rewrite ${command}`.quiet().nothrow();
        const rewritten = String(result.stdout).trim();
        if (rewritten && rewritten !== command) {
          (args as Record<string, unknown>).command = rewritten;
        }
      } catch {
        // RTK is an optimization. Never block the original command on failure.
      }
    },
  };
};
