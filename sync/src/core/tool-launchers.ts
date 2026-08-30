import path from "node:path";
import type { SyncEnv } from "./harness.ts";

export interface ToolLauncherSpec {
  readonly id: string;
  readonly package: string;
  readonly bin: string;
  readonly distTag?: string;
  readonly smokeCheck?: string;
  readonly defaultArgs?: readonly string[];
  readonly configHomeSegments?: readonly string[];
}

/**
 * npm tools that sync launches like harnesses: a generated wrapper under
 * ~/.local/bin, a versioned package cache, and a best-effort sync before
 * launch. Tools have no harness home, instruction file, or skills.
 */
export const TOOL_LAUNCHERS = [
  {
    id: "mcporter",
    package: "mcporter",
    bin: "mcporter",
    configHomeSegments: [".mcporter", "mcporter.json"],
  },
  {
    id: "summarize",
    package: "@steipete/summarize",
    bin: "summarize",
    defaultArgs: [
      "--force-summary",
      "--timestamps",
      "--format",
      "md",
      "--retries",
      "2",
      "--metrics",
      "detailed",
    ],
  },
] as const satisfies readonly ToolLauncherSpec[];

export const toolLauncher = (id: string): ToolLauncherSpec | undefined =>
  TOOL_LAUNCHERS.find((tool) => tool.id === id);

export const toolLauncherDefaultArgs = (
  syncEnv: Pick<SyncEnv, "home">,
  tool: ToolLauncherSpec,
): readonly string[] => {
  const configArgs =
    tool.configHomeSegments === undefined
      ? []
      : ["--config", path.join(syncEnv.home, ...tool.configHomeSegments)];
  return [...configArgs, ...(tool.defaultArgs ?? [])];
};
