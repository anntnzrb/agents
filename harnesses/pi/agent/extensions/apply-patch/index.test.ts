import { afterEach, describe, expect, mock, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

mock.module("@earendil-works/pi-coding-agent", () => ({
  withFileMutationQueue: async <T>(
    _path: string,
    operation: () => Promise<T>,
  ): Promise<T> => operation(),
}));

const { APPLY_PATCH_GRAMMAR, applyPatch, default: applyPatchExtension } =
  await import("./index.js");

const tempDirs: string[] = [];

const createTempDir = async (): Promise<string> => {
  const directory = await mkdtemp(join(tmpdir(), "pi-apply-patch-"));
  tempDirs.push(directory);
  return directory;
};

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map(directory =>
      rm(directory, { recursive: true, force: true }),
    ),
  );
});

describe("apply_patch extension", () => {
  test("registers native grammar sampling and replaces edit for capable GPT models", () => {
    let activeTools = ["read", "bash", "edit", "write"];
    let registeredTool: Record<string, unknown> | undefined;
    const handlers = new Map<string, (event: any, context: any) => void>();

    applyPatchExtension({
      getActiveTools: () => activeTools,
      on: (event: string, handler: (event: any, context: any) => void) => {
        handlers.set(event, handler);
      },
      registerTool: (tool: Record<string, unknown>) => {
        registeredTool = tool;
      },
      setActiveTools: (tools: string[]) => {
        activeTools = tools;
      },
    } as any);

    expect(registeredTool?.name).toBe("apply_patch");
    expect(registeredTool?.executionMode).toBe("sequential");
    expect(registeredTool?.constrainedSampling).toEqual({
      type: "grammar",
      variants: { openai_lark: APPLY_PATCH_GRAMMAR },
    });

    handlers.get("session_start")?.(
      { type: "session_start" },
      {
        model: {
          id: "gpt-5.6-sol",
          compat: { supportsOpenAIGrammarTools: true },
        },
      },
    );
    expect(activeTools).toEqual(["read", "bash", "write", "apply_patch"]);

    handlers.get("model_select")?.(
      {
        type: "model_select",
        model: { id: "deepseek-v4-flash", compat: {} },
      },
      {},
    );
    expect(activeTools).toEqual(["read", "bash", "write", "edit"]);
  });
});

describe("applyPatch", () => {
  test("applies add, update, and delete operations", async () => {
    const cwd = await createTempDir();
    await writeFile(join(cwd, "keep.txt"), "hello\n", "utf8");
    await writeFile(join(cwd, "old.txt"), "delete me\n", "utf8");

    const result = await applyPatch(
      [
        "*** Begin Patch",
        "*** Add File: new.txt",
        "+brand new",
        "*** Update File: keep.txt",
        "@@",
        "-hello",
        "+HELLO",
        "*** Delete File: old.txt",
        "*** End Patch",
      ].join("\n"),
      cwd,
    );

    expect(result).toBe(
      "Success. Updated the following files:\nA new.txt\nM keep.txt\nD old.txt",
    );
    expect(await readFile(join(cwd, "new.txt"), "utf8")).toBe("brand new\n");
    expect(await readFile(join(cwd, "keep.txt"), "utf8")).toBe("HELLO\n");
    await expect(readFile(join(cwd, "old.txt"), "utf8")).rejects.toThrow();
  });

  test("preserves CRLF line endings while updating", async () => {
    const cwd = await createTempDir();
    await writeFile(join(cwd, "windows.txt"), "one\r\ntwo\r\n", "utf8");

    await applyPatch(
      [
        "*** Begin Patch",
        "*** Update File: windows.txt",
        "@@",
        " one",
        "-two",
        "+three",
        "*** End Patch",
      ].join("\n"),
      cwd,
    );

    expect(await readFile(join(cwd, "windows.txt"), "utf8")).toBe(
      "one\r\nthree\r\n",
    );
  });

  test("keeps earlier writes when a later operation fails", async () => {
    const cwd = await createTempDir();
    await writeFile(join(cwd, "first.txt"), "a\n", "utf8");

    await expect(
      applyPatch(
        [
          "*** Begin Patch",
          "*** Update File: first.txt",
          "@@",
          "-a",
          "+A",
          "*** Update File: missing.txt",
          "@@",
          "-x",
          "+y",
          "*** End Patch",
        ].join("\n"),
        cwd,
      ),
    ).rejects.toThrow("Failed to read file to update missing.txt");

    expect(await readFile(join(cwd, "first.txt"), "utf8")).toBe("A\n");
  });

  test("moves an updated file", async () => {
    const cwd = await createTempDir();
    await writeFile(join(cwd, "source.txt"), "before\n", "utf8");

    await applyPatch(
      [
        "*** Begin Patch",
        "*** Update File: source.txt",
        "*** Move to: nested/destination.txt",
        "@@",
        "-before",
        "+after",
        "*** End Patch",
      ].join("\n"),
      cwd,
    );

    await expect(readFile(join(cwd, "source.txt"), "utf8")).rejects.toThrow();
    expect(
      await readFile(join(cwd, "nested/destination.txt"), "utf8"),
    ).toBe("after\n");
  });

  test("does not overwrite existing add or move destinations", async () => {
    const cwd = await createTempDir();
    await writeFile(join(cwd, "source.txt"), "source\n", "utf8");
    await writeFile(join(cwd, "existing.txt"), "kept\n", "utf8");

    await expect(
      applyPatch(
        "*** Begin Patch\n*** Add File: existing.txt\n+lost\n*** End Patch",
        cwd,
      ),
    ).rejects.toThrow("already exists");
    await expect(
      applyPatch(
        [
          "*** Begin Patch",
          "*** Update File: source.txt",
          "*** Move to: existing.txt",
          "@@",
          "-source",
          "+changed",
          "*** End Patch",
        ].join("\n"),
        cwd,
      ),
    ).rejects.toThrow("already exists");

    expect(await readFile(join(cwd, "source.txt"), "utf8")).toBe("source\n");
    expect(await readFile(join(cwd, "existing.txt"), "utf8")).toBe("kept\n");
  });

  test("accepts whitespace-padded top-level markers", async () => {
    const cwd = await createTempDir();
    await writeFile(join(cwd, "file.txt"), "old\n", "utf8");

    await applyPatch(
      "*** Begin Patch  \n  *** Update File: file.txt\n@@\n-old\n+new\n  *** End Patch",
      cwd,
    );

    expect(await readFile(join(cwd, "file.txt"), "utf8")).toBe("new\n");
  });

  test("rejects malformed patches before writing", async () => {
    const cwd = await createTempDir();

    await expect(
      applyPatch(
        "*** Begin Patch\n*** Add File: created.txt\n+created\nnot valid",
        cwd,
      ),
    ).rejects.toThrow("*** End Patch");
    await expect(readFile(join(cwd, "created.txt"), "utf8")).rejects.toThrow();
  });
});
