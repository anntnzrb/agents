import { describe, expect, mock, test } from "bun:test";

mock.module("@earendil-works/pi-coding-agent", () => ({
  VERSION: "0.0.0",
  DEFAULT_MAX_BYTES: 50 * 1024,
  DEFAULT_MAX_LINES: 2000,
  formatSize: (bytes: number) => `${Math.round(bytes / 1024)}KB`,
  keyHint: (_action: string, hint: string) => hint,
  getAgentDir: () => "/tmp/pi-agent",
  truncateHead: (content: string) => ({ content, truncated: false }),
  isToolCallEventType: () => false,
  createReadToolDefinition: () => ({ name: "read", renderShell: "self" }),
  createWriteToolDefinition: () => ({ name: "write", renderShell: "self" }),
  createEditToolDefinition: () => ({ name: "edit", renderShell: "self" }),
  createFindToolDefinition: () => ({ name: "find", renderShell: "self" }),
  createGrepToolDefinition: () => ({ name: "grep", renderShell: "self" }),
}));

mock.module("@earendil-works/pi-tui", () => ({
  Text: class {
    setText() {}
  },
  truncateToWidth: (value: string, _width: number) => value,
  visibleWidth: (value: string) => value.length,
}));

mock.module("@sinclair/typebox", () => ({
  Type: {
    String: () => ({}),
    Optional: (value: unknown) => value,
    Number: () => ({}),
    Boolean: () => ({}),
    Array: () => ({}),
    Object: () => ({}),
  },
}));

const { __test } = await import("./index.js");

const passthroughTheme = {
  fg: (_token: string, text: string) => text,
  bold: (text: string) => text,
};

const tokenTheme = {
  fg: (token: string, text: string) => `<${token}>${text}</${token}>`,
  bold: (text: string) => `**${text}**`,
};

describe("find compact rendering", () => {
  test("call is naked single-line telemetry", () => {
    const text = __test.formatFindCall(
      { pattern: "**/*.ts", paths: ["src"], hidden: false, limit: 20 },
      passthroughTheme,
    );
    expect(text).toBe("◇ find paths:src · **/*.ts · visible · limit:20");
    expect(text.split("\n")).toHaveLength(1);
  });

  test("call includes non-default kind and ignore controls", () => {
    const text = __test.formatFindCall(
      { pattern: "src*", kind: "directory", ignored: true },
      passthroughTheme,
    );
    expect(text).toBe("◇ find . · src* · directory · ignored");
  });

  test("call compacts long paths", () => {
    const text = __test.formatFindCall(
      {
        pattern: "*.ts",
        paths: ["/tmp/llm-agents-scan/opencode/packages/opencode/src/tool"],
      },
      passthroughTheme,
    );
    expect(text).toContain("…/packages/opencode/src/tool");
  });

  test("colors cue/title/pattern separately", () => {
    const text = __test.formatFindCall(
      { pattern: "**/*.ts", paths: ["src"] },
      tokenTheme,
    );
    expect(text).toContain("<muted>◇</muted>");
    expect(text).toContain("<toolTitle>**find**</toolTitle>");
    expect(text).toContain("<muted>paths:src</muted>");
    expect(text).toContain("**/*.ts");
  });

  test("summarizes file count", () => {
    const text = __test.getCollapsedSummary("a.ts\nb.ts", {}, passthroughTheme);
    expect(text).toBe("  ↳ 2 files");
  });

  test("summarizes no matches", () => {
    const text = __test.getCollapsedSummary(
      "No files found matching pattern",
      {},
      passthroughTheme,
    );
    expect(text).toBe("  No files found matching pattern");
  });

  test("summarizes limit and truncation notices", () => {
    const text = __test.getCollapsedSummary(
      "a.ts",
      { resultLimitReached: 1, truncation: { truncated: true } },
      passthroughTheme,
    );
    expect(text).toContain("1 file");
    expect(text).not.toContain("more");
    expect(text).toContain("50KB output limit");
  });
});
