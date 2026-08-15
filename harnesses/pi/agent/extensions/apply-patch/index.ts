import type {
  ExtensionAPI,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { APPLY_PATCH_GRAMMAR } from "./grammar.js";
import { applyPatch, parsePatch } from "./patch.js";

export { APPLY_PATCH_GRAMMAR, applyPatch, parsePatch };

const TOOL_NAME = "apply_patch";
const EDIT_TOOL_NAME = "edit";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const shouldUseApplyPatch = (model: unknown): boolean => {
  if (!isRecord(model) || typeof model["id"] !== "string") return false;
  const compat = model["compat"];
  return (
    /(^|\/)gpt-/i.test(model["id"]) &&
    isRecord(compat) &&
    compat["supportsOpenAIGrammarTools"] === true
  );
};

const parameters = {
  type: "object",
  properties: {
    input: { type: "string" },
  },
  required: ["input"],
  additionalProperties: false,
} as const;

export default function applyPatchExtension(pi: ExtensionAPI): void {
  let displacedEdit = false;

  const reconcileTools = (model: unknown): void => {
    const active = pi.getActiveTools();
    if (shouldUseApplyPatch(model)) {
      displacedEdit ||= active.includes(EDIT_TOOL_NAME);
      const next = active.filter(
        name => name !== EDIT_TOOL_NAME && name !== TOOL_NAME,
      );
      next.push(TOOL_NAME);
      pi.setActiveTools(next);
      return;
    }

    const next = active.filter(name => name !== TOOL_NAME);
    if (displacedEdit && !next.includes(EDIT_TOOL_NAME)) next.push(EDIT_TOOL_NAME);
    displacedEdit = false;
    pi.setActiveTools(next);
  };

  const tool = {
    name: TOOL_NAME,
    label: TOOL_NAME,
    description:
      "Apply a Codex patch envelope beginning with '*** Begin Patch' and ending with '*** End Patch'. Use relative file paths and Add, Delete, or Update file sections.",
    promptSnippet: "Apply multi-file Codex patches with native freeform grammar",
    promptGuidelines: [
      "Use apply_patch instead of edit for file changes.",
      "Patch paths must be relative to the working directory.",
      "Prefix every added file line with + and include context around updates.",
    ],
    parameters,
    constrainedSampling: {
      type: "grammar",
      variants: { openai_lark: APPLY_PATCH_GRAMMAR },
    },
    executionMode: "sequential",
    async execute(
      _toolCallId: string,
      params: { readonly input: string },
      signal: AbortSignal | undefined,
      _onUpdate: unknown,
      context: { readonly cwd: string },
    ) {
      return {
        content: [
          {
            type: "text",
            text: await applyPatch(params.input, context.cwd, signal),
          },
        ],
      };
    },
  } as unknown as ToolDefinition;

  pi.registerTool(tool);
  pi.on("session_start", (_event, context) => reconcileTools(context.model));
  pi.on("model_select", event => reconcileTools(event.model));
}
