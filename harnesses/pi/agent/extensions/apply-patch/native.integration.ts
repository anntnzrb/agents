import { afterEach, expect, test } from "bun:test";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type { ExtensionAPI, ExtensionToolContext } from "@earendil-works/pi-coding-agent";
import { createApplyPatchTool } from "./index.ts";

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

const executeFile = promisify(execFile);
const exec: ExtensionAPI["exec"] = async (command, args, options) => {
  try {
    const result = await executeFile(command, args, { cwd: options?.cwd, signal: options?.signal });
    return { ...result, code: 0, killed: false };
  } catch (error) {
    if (!(error instanceof Error) || !("stdout" in error) || !("stderr" in error)) throw error;
    return {
      stdout: String(error.stdout), stderr: String(error.stderr), code: 1,
      killed: "killed" in error && error.killed === true,
    };
  }
};

function context(cwd: string, id = "gpt-6.1-sol") {
  return { cwd, model: { id } } as ExtensionToolContext;
}

test("adds, updates with anchors and EOF context, moves, and deletes using the native engine", async () => {
  const cwd = await workspace();
  const tool = createApplyPatchTool({ exec });
  const run = (input: string) => tool.execute("test", { input }, undefined, undefined, context(cwd));
  await run("*** Begin Patch\n*** Add File: nested/example.txt\n+header\n+old\n+tail\n*** Add File: gone.txt\n+delete me\n*** End Patch");
  expect(await readFile(join(cwd, "nested/example.txt"), "utf8")).toBe("header\nold\ntail\n");
  await run("*** Begin Patch\n*** Update File: nested/example.txt\n*** Move to: moved.txt\n@@ header\n-old\n+new\n tail\n*** End of File\n*** Delete File: gone.txt\n*** End Patch");
  expect(await readFile(join(cwd, "moved.txt"), "utf8")).toBe("header\nnew\ntail\n");
  expect(await readFile(join(cwd, "gone.txt")).catch((error) => error.code)).toBe("ENOENT");
  expect(await readFile(join(cwd, "nested/example.txt")).catch((error) => error.code)).toBe("ENOENT");
}, 30000);

test("reports malformed patches and failed context as tool failures", async () => {
  const cwd = await workspace();
  await writeFile(join(cwd, "example.txt"), "original\n");
  const tool = createApplyPatchTool({ exec });
  for (const input of ["garbage", "*** Begin Patch\n*** Update File: example.txt\n@@\n-missing\n+changed\n*** End Patch"]) {
    await expect(tool.execute("test", { input }, undefined, undefined, context(cwd))).rejects.toThrow("apply_patch failed");
  }
  expect(await readFile(join(cwd, "example.txt"), "utf8")).toBe("original\n");
}, 30000);
