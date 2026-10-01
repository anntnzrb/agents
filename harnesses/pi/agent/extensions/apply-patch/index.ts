import { mkdtemp, realpath, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { Type } from "@earendil-works/pi-ai";
import {
  defineTool,
  truncateHead,
  withFileMutationQueue,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { PATCH_GRAMMAR } from "./grammar.ts";
import { CODEX_GPT_MODELS } from "./model-catalog.ts";
import { registerCompactCodemode } from "./codemode-preview.ts";

export function supportsApplyPatch(model: { id: string } | undefined): boolean {
  if (!model) return false;
  // Match Codex's longest-prefix lookup and single-provider namespace fallback.
  // Unknown models have no apply_patch_tool_type in Codex's fallback metadata.
  const find = (id: string) => CODEX_GPT_MODELS
    .filter(({ slug }) => id.startsWith(slug))
    .sort((a, b) => b.slug.length - a.slug.length)[0];
  const direct = find(model.id);
  if (direct) return direct.apply_patch_tool_type !== null;
  const namespaced = /^[A-Za-z0-9_-]+\/([^/]+)$/.exec(model.id);
  const candidate = namespaced ? find(namespaced[1]!) : undefined;
  return candidate !== undefined && candidate.apply_patch_tool_type !== null;
}

async function canonicalPath(path: string): Promise<string> {
  try {
    return await realpath(path);
  } catch (error) {
    if (!(error instanceof Error) || !("code" in error) || error.code !== "ENOENT") {
      throw error;
    }
    // New files still need the real parent, including symlinked directories.
    return join(await canonicalPath(dirname(path)), basename(path));
  }
}

export async function patchTargets(input: string, cwd: string): Promise<string[]> {
  const paths = [...input.matchAll(/^[^\S\r\n]*\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)\r?$/gm)]
    .map((match) => resolve(cwd, match[1]!.trimEnd()));
  return [...new Set(await Promise.all(paths.map(canonicalPath)))].sort();
}

async function withMutationQueues<T>(paths: string[], run: () => Promise<T>): Promise<T> {
  const lock = (index: number): Promise<T> => {
    const path = paths[index];
    return path === undefined ? run() : withFileMutationQueue(path, () => lock(index + 1));
  };
  return lock(0);
}

async function boundedOutput(output: string): Promise<string> {
  const truncated = truncateHead(output);
  if (!truncated.truncated) return truncated.content;
  const directory = await mkdtemp(join(tmpdir(), "pi-apply-patch-"));
  const path = join(directory, "output.txt");
  await writeFile(path, output, "utf8");
  return `${truncated.content}\n\n[Output truncated. Full output: ${path}]`;
}

export function createApplyPatchTool(pi: Pick<ExtensionAPI, "exec">) {
  return defineTool({
    name: "apply_patch",
    label: "apply_patch",
    description: `Apply a Codex patch to add, update, move, or delete files. Pass the full patch as input:
*** Begin Patch
*** Update File: path/to/file
@@
-old line
+new line
*** End Patch
Use *** Add File: path with + prefixed lines, or *** Delete File: path.
For moves, put *** Move to: destination immediately after *** Update File: source and include a hunk.
Paths are relative to the working directory. Use context lines prefixed with a space; @@ may include a function or class anchor. Use *** End of File after a hunk that must match at EOF.
Failures or cancellation may leave earlier file changes applied; inspect the reported files before retrying.`,
    promptSnippet: "Add, edit, move, and delete files with Codex patch syntax",
    promptGuidelines: [
      "Use apply_patch for file changes. Read existing files before patching and re-read files changed by another tool or formatter.",
      "Give apply_patch hunks at least three unchanged context lines on each side when available. For repeated blocks, use more context and unique @@ function or class anchors. Anchor insert-only hunks with unchanged context.",
      "Do not duplicate overlapping context between apply_patch hunks. After an apply_patch failure, inspect the reported files before retrying; earlier operations may already have applied.",
    ],
    parameters: Type.Object({ input: Type.String({ description: "Full *** Begin Patch / *** End Patch text" }) }),
    constrainedSampling: { type: "grammar", variants: { openai_lark: PATCH_GRAMMAR } },
    exposure: "direct",
    defaultActive: false,
    executionMode: "sequential",
    async execute(_id, { input }, signal, _onUpdate, ctx) {
      if (!supportsApplyPatch(ctx.model)) throw new Error("apply_patch is available only for GPT models supported by the Codex catalog");
      signal?.throwIfAborted();
      const paths = await patchTargets(input, ctx.cwd);
      return withMutationQueues(paths, async () => {
        signal?.throwIfAborted();
        // Use the installed Codex engine, without a shell or a model request.
        const result = await pi.exec("codex", ["--codex-run-as-apply-patch", input], { cwd: ctx.cwd, signal });
        const output = await boundedOutput([result.stdout, result.stderr].filter(Boolean).join("\n"));
        if (result.killed || signal?.aborted) {
          throw new Error(`apply_patch cancelled. Earlier changes may have been applied.\n${output}`);
        }
        if (result.code !== 0) {
          throw new Error(`apply_patch failed (exit ${result.code}). Earlier changes may have been applied.\n${output || "Ensure the Codex CLI is installed and available on PATH."}`);
        }
        return { content: [{ type: "text", text: output }], details: { paths } };
      });
    },
  });
}

export default function applyPatch(pi: ExtensionAPI) {
  registerCompactCodemode(pi);
  const tool = createApplyPatchTool(pi);
  // Initially inactive, but declarable so --tools apply_patch can select it.
  // session_start hides it before any non-GPT model request.
  pi.registerTool(tool);
  const replacedTools = new Set<string>();

  const selectTools = (model: { id: string } | undefined) => {
    // --tools / --exclude-tools can remove the tool from Pi's registry entirely.
    if (!pi.getAllTools().some(({ name }) => name === tool.name)) return;
    const current = pi.getActiveTools();
    const active = current.filter((name) => name !== tool.name);
    if (supportsApplyPatch(model)) {
      const canMutate = current.some((name) => name === tool.name || name === "edit" || name === "write");
      for (const name of active) {
        if (name === "edit" || name === "write") replacedTools.add(name);
      }
      pi.registerTool({ ...tool, exposure: canMutate ? "direct" : "hidden" });
      pi.setActiveTools([
        ...active.filter((name) => name !== "edit" && name !== "write"),
        ...(canMutate ? [tool.name] : []),
      ]);
    } else {
      pi.registerTool({ ...tool, exposure: "hidden" });
      pi.setActiveTools([...new Set([...active, ...replacedTools])]);
      replacedTools.clear();
    }
  };

  pi.on("session_start", (_event, ctx) => selectTools(ctx.model));
  pi.on("model_select", (event) => selectTools(event.model));
}
