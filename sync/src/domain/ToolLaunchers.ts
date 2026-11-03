import { Schema } from "effect"

import { joinPath } from "#domain/PathText"

export const ToolLauncherSpec = Schema.Struct({
  id: Schema.String,
  package: Schema.String,
  bin: Schema.String,
  defaultArgs: Schema.Array(Schema.String),
  configHomeSegments: Schema.Array(Schema.String),
})
export type ToolLauncherSpec = typeof ToolLauncherSpec.Type

export const TOOL_LAUNCHERS: readonly ToolLauncherSpec[] = [
  {
    id: "mcporter",
    package: "mcporter",
    bin: "mcporter",
    defaultArgs: [],
    configHomeSegments: [".mcporter", "mcporter.json"],
  },
  { id: "paseo", package: "@getpaseo/cli", bin: "paseo", defaultArgs: [], configHomeSegments: [] },
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
    configHomeSegments: [],
  },
]

export const toolLauncher = (id: string): ToolLauncherSpec | undefined => {
  for (const tool of TOOL_LAUNCHERS) {
    if (tool.id === id) {
      return tool
    }
  }
  return undefined
}
export const toolLauncherDefaultArgs = (
  syncEnv: { readonly home: string },
  tool: ToolLauncherSpec,
): string[] =>
  tool.configHomeSegments.length > 0
    ? ["--config", joinPath(syncEnv.home, ...tool.configHomeSegments), ...tool.defaultArgs]
    : [...tool.defaultArgs]
