import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";

const REWRITE_TIMEOUT_MS = 2_000;
const MIN_SUPPORTED_RTK_MINOR = 23;
const RTK_SYSTEM_GUIDANCE =
  "RTK automatically filters supported shell commands. Prefer native structured tools, use raw commands for exact or machine-readable output, and rerun raw when filtered output hides diagnostic evidence.";

const parseSemver = (raw: string): [number, number, number] | null => {
  const match = raw.trim().match(/(\d+)\.(\d+)\.(\d+)/);
  if (!match) return null;
  return [
    Number.parseInt(match[1], 10),
    Number.parseInt(match[2], 10),
    Number.parseInt(match[3], 10),
  ];
};

const rewriteCommand = async (
  pi: ExtensionAPI,
  command: string,
  signal?: AbortSignal,
): Promise<string | null> => {
  const result = await pi.exec("rtk", ["rewrite", command], {
    timeout: REWRITE_TIMEOUT_MS,
    signal,
  });
  if (result.killed || (result.code !== 0 && result.code !== 3)) return null;
  return result.stdout.trim() || null;
};

export default async function rtkExtension(pi: ExtensionAPI): Promise<void> {
  const version = await pi.exec("rtk", ["--version"], {
    timeout: REWRITE_TIMEOUT_MS,
  });
  if (version.code !== 0) {
    console.warn("[rtk] rtk binary not found in PATH - extension disabled");
    return;
  }

  const parsed = parseSemver(version.stdout.replace(/^rtk\s+/, ""));
  if (parsed?.[0] === 0 && parsed[1] < MIN_SUPPORTED_RTK_MINOR) {
    console.warn(`[rtk] ${version.stdout.trim()} is too old (need >= 0.23.0) - extension disabled`);
    return;
  }

  pi.on("before_agent_start", event => ({
    systemPrompt: `${event.systemPrompt}\n\n${RTK_SYSTEM_GUIDANCE}`,
  }));

  pi.on("tool_call", async (event, context) => {
    try {
      if (!isToolCallEventType("bash", event)) return;

      const command = event.input.command;
      if (typeof command !== "string" || command.trim() === "") return;
      if (command.startsWith("rtk ") || process.env.RTK_DISABLED === "1") return;

      const rewritten = await rewriteCommand(pi, command, context.signal);
      if (rewritten && rewritten !== command) event.input.command = rewritten;
    } catch (error) {
      console.warn(
        "[rtk] unexpected error in tool_call handler; passing through command",
        error,
      );
    }
  });
}
