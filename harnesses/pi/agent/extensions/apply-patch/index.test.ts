import { afterEach, expect, test } from "bun:test";
import { mkdtemp, mkdir, readFile, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { convertResponsesTools } from "@earendil-works/pi-ai/api/openai-responses-shared";
import { createGrammarToolInputProperties } from "@earendil-works/pi-ai/api/constrained-sampling";
import { withFileMutationQueue, type ExtensionAPI, type ExtensionToolContext } from "@earendil-works/pi-coding-agent";
import applyPatch, { createApplyPatchTool, supportsApplyPatch, patchTargets } from "./index.ts";
import { PATCH_GRAMMAR } from "./grammar.ts";

const directories: string[] = [];
afterEach(async () => {
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

async function workspace() {
  // Resolve platform temp symlinks (macOS /var -> /private/var) so expected paths are canonical.
  const cwd = await realpath(await mkdtemp(join(tmpdir(), "pi-apply-patch-test-")));
  directories.push(cwd);
  return cwd;
}

const exec: ExtensionAPI["exec"] = async () => {
  throw new Error("Native execution belongs to native.integration.ts");
};

function context(cwd: string, id = "gpt-6.1-sol") {
  return { cwd, model: { id } } as ExtensionToolContext;
}

test("uses Codex catalog capability and prefix lookup instead of guessing from GPT names", () => {
  for (const id of ["gpt-5.5", "gpt-6.1-sol", "openai/gpt-6-astra", "command-code/gpt-6.1-sol", "gpt-5.5-2026-09-01", "gpt-daybreak-blue-latest"]) {
    expect(supportsApplyPatch({ id })).toBe(true);
  }
  for (const id of ["claude-sonnet-4", "deepseek-v4", "o3", "codex-mini-latest", "my-gpt-5", "gpt-fake", "gpt-4.1", "openai/gpt-oss-120b", "gpt-99", "gpt-5", "gpt-5.4", "GPT-6.1-SOL", "pool/openai/gpt-6.1-sol", "/gpt-6.1-sol", "bad.namespace/gpt-6.1-sol", "codex-auto-review"]) {
    expect(supportsApplyPatch({ id })).toBe(false);
  }
  expect(supportsApplyPatch(undefined)).toBe(false);
});

test("Pi emits a Lark custom tool for capable Responses models and a JSON function otherwise", () => {
  const tool = createApplyPatchTool({ exec });
  expect(convertResponsesTools([tool], { supportsOpenAIGrammarTools: true })).toEqual([{
    type: "custom", name: "apply_patch", description: tool.description,
    format: { type: "grammar", syntax: "lark", definition: PATCH_GRAMMAR },
  }]);
  expect(createGrammarToolInputProperties([tool], true).get("apply_patch")).toBe("input");
  expect(convertResponsesTools([tool], { supportsOpenAIGrammarTools: false })[0]?.type).toBe("function");
  expect(createGrammarToolInputProperties([tool], false).size).toBe(0);
});

test("switches tools on startup and model selection, preserving unrelated tools and disabled write", () => {
  let active = ["read", "bash", "edit", "custom"];
  let allowed = true;
  const tools: ReturnType<typeof createApplyPatchTool>[] = [];
  const handlers = new Map<string, (event: { model?: { id: string } }, ctx: { model?: { id: string } }) => void>();
  // This fake implements only the host methods used by the extension.
  applyPatch({
    exec,
    registerTool: (tool: ReturnType<typeof createApplyPatchTool>) => tools.push(tool),
    getAllTools: () => allowed ? [{ name: "apply_patch" }] : [],
    getActiveTools: () => active,
    setActiveTools: (names: string[]) => { active = names; },
    on: (event: string, handler: (event: { model?: { id: string } }, ctx: { model?: { id: string } }) => void) => {
      handlers.set(event, handler);
    },
  } as unknown as ExtensionAPI);
  expect(tools.at(-1)?.defaultActive).toBe(false);
  handlers.get("session_start")!({}, { model: { id: "claude" } });
  expect(tools.at(-1)?.exposure).toBe("hidden");
  expect(active).toEqual(["read", "bash", "edit", "custom"]);
  handlers.get("session_start")!({}, { model: { id: "gpt-5.5" } });
  expect(active).toEqual(["read", "bash", "custom", "apply_patch"]);
  expect(tools.at(-1)?.exposure).toBe("direct");
  handlers.get("model_select")!({ model: { id: "openai/gpt-6.1-sol" } }, {});
  active.push("another");
  handlers.get("model_select")!({ model: { id: "claude-sonnet-4" } }, {});
  expect(active).toEqual(["read", "bash", "custom", "another", "edit"]);
  expect(tools.at(-1)?.exposure).toBe("hidden");
  handlers.get("model_select")!({ model: { id: "deepseek-v4" } }, {});
  expect(active.filter((name) => name === "edit")).toHaveLength(1);
  active = ["read", "write"];
  handlers.get("model_select")!({ model: { id: "gpt-5.5" } }, {});
  expect(active).toEqual(["read", "apply_patch"]);
  handlers.get("model_select")!({ model: { id: "claude" } }, {});
  expect(active).toEqual(["read", "write"]);
  active = ["read"];
  handlers.get("model_select")!({ model: { id: "gpt-5.5" } }, {});
  expect(active).toEqual(["read"]);
  expect(tools.at(-1)?.exposure).toBe("hidden");
  active = ["read", "apply_patch"];
  handlers.get("model_select")!({ model: { id: "gpt-5.5" } }, {});
  expect(active).toEqual(["read", "apply_patch"]);
  allowed = false;
  active = ["read", "edit", "write"];
  handlers.get("model_select")!({ model: { id: "gpt-5.5" } }, {});
  expect(active).toEqual(["read", "edit", "write"]);
});

test("resolves aliases and both sides of moves into unique sorted mutation targets", async () => {
  const cwd = await workspace();
  await mkdir(join(cwd, "real"));
  await symlink(join(cwd, "real"), join(cwd, "alias"));
  await writeFile(join(cwd, "real/file.txt"), "old\n");
  const paths = await patchTargets("*** Begin Patch\n*** Update File: alias/file.txt\n*** Move to: alias/new/deep.txt\n@@\n-old\n+new\n*** Update File: real/file.txt\n@@\n-new\n+final\n*** End Patch", cwd);
  expect(paths).toEqual([join(cwd, "real/file.txt"), join(cwd, "real/new/deep.txt")]);
  expect(await patchTargets("  *** Add File: alias/ padded.txt  \r\n", cwd)).toEqual([join(cwd, "real/ padded.txt")]);
});

test("waits for Pi's file mutation queue and checks cancellation again before executing", async () => {
  const cwd = await workspace();
  const path = join(cwd, "example.txt");
  await writeFile(path, "original\n");
  let release!: () => void;
  let locked!: () => void;
  const acquired = new Promise<void>((resolve) => { locked = resolve; });
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const blocker = withFileMutationQueue(path, async () => { locked(); await gate; });
  await acquired;
  let executed = false;
  const controller = new AbortController();
  const tool = createApplyPatchTool({ exec: async () => {
    executed = true;
    return { stdout: "", stderr: "", code: 0, killed: false };
  } });
  const pending = tool.execute("test", { input: "*** Begin Patch\n*** Delete File: example.txt\n*** End Patch" }, controller.signal, undefined, context(cwd));
  // Let target resolution finish while the mutation queue is occupied.
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(executed).toBe(false);
  controller.abort();
  release();
  await blocker;
  await expect(pending).rejects.toThrow();
  expect(executed).toBe(false);
  expect(await readFile(path, "utf8")).toBe("original\n");
});

test("rejects non-GPT calls and forwards cancellation and cwd to the host executor", async () => {
  const cwd = await workspace();
  const controller = new AbortController();
  let calls = 0;
  const tool = createApplyPatchTool({ exec: async (command, args, options) => {
    calls++;
    expect(command).toBe("codex");
    expect(args[0]).toBe("--codex-run-as-apply-patch");
    expect(options).toEqual({ cwd, signal: controller.signal });
    return { stdout: "partial", stderr: "", code: 0, killed: true };
  } });
  await expect(tool.execute("test", { input: "garbage" }, undefined, undefined, context(cwd, "claude"))).rejects.toThrow("only for GPT");
  expect(calls).toBe(0);
  await expect(tool.execute("test", { input: "garbage" }, controller.signal, undefined, context(cwd))).rejects.toThrow("cancelled");
  expect(calls).toBe(1);
});

test("truncates success and failure output and stores the complete output", async () => {
  const cwd = await workspace();
  const output = "a line\n".repeat(3000);
  for (const code of [0, 1]) {
    const tool = createApplyPatchTool({ exec: async () => ({ stdout: output, stderr: "", code, killed: false }) });
    let text: string;
    try {
      const result = await tool.execute("test", { input: "garbage" }, undefined, undefined, context(cwd));
      const content = result.content[0];
      if (content?.type !== "text") throw new Error("Expected text result");
      text = content.text;
    } catch (error) {
      if (!(error instanceof Error)) throw error;
      text = error.message;
    }
    expect(text).toContain("Output truncated");
    const path = text.match(/Full output: (.+)\]/)?.[1];
    if (!path) throw new Error("Expected full output path");
    expect(await readFile(path, "utf8")).toBe(output);
    directories.push(join(path, ".."));
  }
});
