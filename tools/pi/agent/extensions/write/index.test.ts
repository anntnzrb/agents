import { describe, expect, mock, test } from "bun:test";
import {
  lstatSync,
  linkSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

mock.module("@earendil-works/pi-coding-agent", () => ({
  VERSION: "0.0.0",
  DEFAULT_MAX_BYTES: 50 * 1024,
  DEFAULT_MAX_LINES: 2000,
  formatSize: (bytes: number) => `${bytes}B`,
  keyHint: (_action: string, hint: string) => hint,
  getAgentDir: () => "/tmp/pi-agent",
  truncateHead: (content: string) => ({ content, truncated: false }),
  isToolCallEventType: () => false,
  createReadToolDefinition: () => ({ name: "read", renderShell: "self" }),
  createWriteToolDefinition: (
    cwd: string,
    options?: {
      operations?: {
        mkdir: (dir: string) => Promise<void>;
        writeFile: (filePath: string, content: string) => Promise<void>;
      };
    },
  ) => ({
    name: "write",
    async execute(
      _toolCallId: string,
      input: { path: string; content: string },
    ) {
      const filePath = input.path.startsWith("/")
        ? input.path
        : join(cwd, input.path);
      await options?.operations?.mkdir(dirname(filePath));
      await options?.operations?.writeFile(filePath, input.content);
      return {
        content: [
          {
            type: "text",
            text: `Successfully wrote ${input.content.length} bytes to ${input.path}`,
          },
        ],
        details: undefined,
      };
    },
  }),
  createEditToolDefinition: () => ({ name: "edit", renderShell: "self" }),
  createFindToolDefinition: () => ({ name: "find", renderShell: "self" }),
  createGrepToolDefinition: () => ({ name: "grep", renderShell: "self" }),
}));

class MockText {
  text = "";
  setText(value: string) {
    this.text = value;
  }
}

mock.module("@earendil-works/pi-tui", () => ({
  Text: MockText,
  truncateToWidth: (value: string, _width: number) => value,
  visibleWidth: (value: string) => value.length,
}));

const { __test, default: writeExtension } = await import("./index.js");

const passthroughTheme = {
  fg: (_token: string, text: string) => text,
  bold: (text: string) => text,
};

const tokenTheme = {
  fg: (token: string, text: string) => `<${token}>${text}</${token}>`,
  bold: (text: string) => `**${text}**`,
};

describe("write content stats", () => {
  test("handles empty and newline-only payloads", () => {
    expect(__test.getContentStats("")).toEqual({ bytes: 0, lines: 0 });
    expect(__test.getContentStats("\n")).toEqual({ bytes: 1, lines: 0 });
    expect(__test.getContentStats("\r\n")).toEqual({ bytes: 2, lines: 0 });
  });

  test("counts lines without allocating splits", () => {
    expect(__test.getContentStats("a").lines).toBe(1);
    expect(__test.getContentStats("a\n").lines).toBe(1);
    expect(__test.getContentStats("a\r\n").lines).toBe(1);
    expect(__test.getContentStats("a\nb\n").lines).toBe(2);
    expect(__test.getContentStats("a\nb").lines).toBe(2);
  });

  test("reports utf8 byte length", () => {
    const payload = "α\nβ";
    expect(__test.getContentStats(payload).bytes).toBe(
      Buffer.byteLength(payload, "utf8"),
    );
  });
});

describe("write execution hardening", () => {
  const makeTempDir = () =>
    join(
      tmpdir(),
      `write-exec-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    );

  test("writes atomically and creates parent directories", async () => {
    const dir = makeTempDir();
    const filePath = join(dir, "nested", "file.txt");
    try {
      const result = await __test.executeWrite(dir, {
        path: filePath,
        content: "new content",
      });
      expect(readFileSync(filePath, "utf8")).toBe("new content");
      expect(result.content[0].text).toContain("Successfully wrote 11 bytes");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("expectedHash allows matching current content", async () => {
    const dir = makeTempDir();
    const filePath = join(dir, "file.txt");
    try {
      mkdirSync(dirname(filePath), { recursive: true });
      writeFileSync(filePath, "old");
      await __test.executeWrite(dir, {
        path: filePath,
        content: "new",
        expectedHash: __test.sha256(Buffer.from("old")),
      });
      expect(readFileSync(filePath, "utf8")).toBe("new");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("expectedHash rejects stale writes and preserves current content", async () => {
    const dir = makeTempDir();
    const filePath = join(dir, "file.txt");
    try {
      mkdirSync(dirname(filePath), { recursive: true });
      writeFileSync(filePath, "external edit");
      await expect(
        __test.executeWrite(dir, {
          path: filePath,
          content: "stale overwrite",
          expectedHash: __test.sha256(Buffer.from("old")),
        }),
      ).rejects.toThrow("Hash mismatch");
      expect(readFileSync(filePath, "utf8")).toBe("external edit");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("atomicWriteFile leaves no temp file on success", async () => {
    const dir = makeTempDir();
    const filePath = join(dir, "file.txt");
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(filePath, "old");
      await __test.atomicWriteFile(filePath, "new");
      expect(readFileSync(filePath, "utf8")).toBe("new");
      expect(
        readdirSync(dir).filter((entry) => entry.startsWith(".pi-write-"))
          .length,
      ).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("atomicWriteFile follows symlinks instead of replacing them", async () => {
    const dir = makeTempDir();
    const targetPath = join(dir, "target.txt");
    const linkPath = join(dir, "link.txt");
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(targetPath, "old");
      symlinkSync(targetPath, linkPath);
      await __test.atomicWriteFile(linkPath, "new");
      expect(lstatSync(linkPath).isSymbolicLink()).toBe(true);
      expect(readlinkSync(linkPath)).toBe(targetPath);
      expect(readFileSync(targetPath, "utf8")).toBe("new");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("atomicWriteFile preserves dangling symlinks when target parent exists", async () => {
    const dir = makeTempDir();
    const targetPath = join(dir, "missing-target.txt");
    const linkPath = join(dir, "dangling-link.txt");
    try {
      mkdirSync(dir, { recursive: true });
      symlinkSync(targetPath, linkPath);
      await __test.atomicWriteFile(linkPath, "new");
      expect(lstatSync(linkPath).isSymbolicLink()).toBe(true);
      expect(readlinkSync(linkPath)).toBe(targetPath);
      expect(readFileSync(targetPath, "utf8")).toBe("new");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("atomicWriteFile preserves hardlink semantics with direct fallback", async () => {
    const dir = makeTempDir();
    const filePath = join(dir, "file.txt");
    const linkPath = join(dir, "hardlink.txt");
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(filePath, "old");
      linkSync(filePath, linkPath);
      await __test.atomicWriteFile(filePath, "new");
      expect(readFileSync(filePath, "utf8")).toBe("new");
      expect(readFileSync(linkPath, "utf8")).toBe("new");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("write compact rendering", () => {
  test("call is naked single-line telemetry", () => {
    const text = __test.buildCollapsedWriteCallText(
      { path: "src/foo.ts", content: "a\nb" },
      "+",
      passthroughTheme,
    );
    expect(text).toBe("▣ write + src/foo.ts · 3B · 2 lines");
    expect(text.split("\n")).toHaveLength(1);
  });

  test("colors cue/title/path/marker separately", () => {
    const text = __test.buildCollapsedWriteCallText(
      { path: "src/foo.ts", content: "a" },
      "+",
      tokenTheme,
    );
    expect(text).toContain("<muted>▣</muted>");
    expect(text).toContain("<toolTitle>**write**</toolTitle>");
    expect(text).toContain("<muted>src/foo.ts</muted>");
    expect(text).toContain("<toolDiffAdded>+</toolDiffAdded>");
    expect(text).toContain("1B");
    expect(text).toContain("1 line");
    expect(text).not.toContain("<text>1B</text>");
  });

  test("colors update marker as warning", () => {
    expect(__test.formatWriteMarker("~", tokenTheme)).toBe(
      "<warning>~</warning>",
    );
  });

  test("uses naked self shell", () => {
    let registered: any;
    writeExtension({
      registerTool: (tool: unknown) => (registered = tool),
    } as any);
    expect(registered.renderShell).toBe("self");
  });

  test("preserves marker after execution starts", () => {
    let registered: any;
    writeExtension({
      registerTool: (tool: unknown) => (registered = tool),
    } as any);

    const dir = join(
      tmpdir(),
      `write-marker-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    );
    mkdirSync(dir, { recursive: true });
    const filePath = join(dir, "file.txt");
    writeFileSync(filePath, "existing");

    const context = {
      expanded: false,
      executionStarted: false,
      argsComplete: false,
      state: {},
      cwd: dir,
      lastComponent: new MockText(),
    };

    const first = registered.renderCall(
      { path: filePath, content: "payload" },
      passthroughTheme,
      context,
    ) as MockText;
    expect(first.text).toContain("~");

    rmSync(filePath, { force: true });
    context.executionStarted = true;
    const second = registered.renderCall(
      { path: filePath, content: "payload" },
      passthroughTheme,
      context,
    ) as MockText;
    expect(second.text).toContain("~");

    rmSync(dir, { recursive: true, force: true });
  });

  test("classifies late streamed args after execution starts", () => {
    let registered: any;
    writeExtension({
      registerTool: (tool: unknown) => (registered = tool),
    } as any);

    const dir = join(
      tmpdir(),
      `write-late-marker-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    );
    mkdirSync(dir, { recursive: true });
    const filePath = join(dir, "file.txt");
    writeFileSync(filePath, "existing");

    try {
      const context = {
        expanded: false,
        executionStarted: true,
        argsComplete: false,
        state: {},
        cwd: dir,
        lastComponent: new MockText(),
      };

      const rendered = registered.renderCall(
        { path: filePath, content: "payload" },
        passthroughTheme,
        context,
      ) as MockText;
      expect(rendered.text).toContain("~");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
