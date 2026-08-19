import { describe, expect, mock, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Effect } from "effect";

mock.module("@earendil-works/pi-coding-agent", () => ({
  VERSION: "0.0.0",
  DEFAULT_MAX_BYTES: 50 * 1024,
  formatSize: (bytes: number) => `${bytes}B`,
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
    text = "";
    setText(value: string) {
      this.text = value;
    }
  },
  truncateToWidth: (value: string, width: number) => value.slice(0, width),
  visibleWidth: (value: string) => value.length,
}));

const { clearFooterContributionsForTests, registerFooterContribution } =
  await import("../_shared/footer-contributions.js");
const { __test, default: footerExtension } = await import("./index.js");

describe("footer helpers", () => {
  test("detects stale extension errors", () => {
    expect(
      __test.isStaleExtensionError(
        new Error(
          "This extension instance is stale after session replacement or reload.",
        ),
      ),
    ).toBe(true);
    expect(__test.isStaleExtensionError(new Error("boom"))).toBe(false);
    expect(__test.isStaleExtensionError("boom")).toBe(false);
  });

  test("computes pollution percent for compaction summary blocks", () => {
    expect(__test.calculatePollutionPercent("")).toBeNull();
    expect(__test.calculatePollutionPercent("hello world")).toBe(0);

    const summary = "abc<read-files>one\ntwo</read-files>def";
    const block = "<read-files>one\ntwo</read-files>";
    const expected = Math.round((100 * block.length) / summary.length);
    expect(__test.calculatePollutionPercent(summary)).toBe(expected);
  });

  test("does not expose pi-goal-specific helpers", () => {
    expect("getLatestGoal" in __test).toBe(false);
    expect("buildGoalBadge" in __test).toBe(false);
  });

  test("treats malformed settings JSON as absent", async () => {
    const dir = await mkdtemp(join(tmpdir(), "footer-settings-"));
    const path = join(dir, "settings.json");
    try {
      await writeFile(path, "{malformed", "utf8");
      await expect(Effect.runPromise(__test.readJsonFileEffect(path))).resolves.toBeUndefined();
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});

describe("footer stale fallback", () => {
  const createHarness = async (
    initiallyStale = false,
    entries: unknown[] = [],
  ) => {
    clearFooterContributionsForTests();
    let sessionStartHandler:
      | ((event: unknown, ctx: any) => void | Promise<void>)
      | undefined;
    const pi = {
      on: (
        event: string,
        handler: (event: unknown, ctx: any) => void | Promise<void>,
      ) => {
        if (event === "session_start") sessionStartHandler = handler;
      },
      getThinkingLevel: () => "off",
    };
    footerExtension(pi as any);

    let footerFactory: ((...args: any[]) => any) | undefined;
    let stale = initiallyStale;
    const ctx = {
      hasUI: true,
      cwd: "/tmp",
      sessionManager: {
        getEntries: () => entries,
        getLeafId: () => null,
      },
      ui: {
        setFooter: (factory: (...args: any[]) => any) => {
          footerFactory = factory;
        },
      },
      getContextUsage: () => {
        if (stale) {
          throw new Error(
            "This extension instance is stale after session replacement or reload.",
          );
        }
        return { tokens: 10, contextWindow: 100, percent: 10 };
      },
      model: { id: "m", reasoning: false, contextWindow: 100 },
    };

    await sessionStartHandler?.({}, ctx);
    expect(footerFactory).toBeDefined();
    const footer = footerFactory?.(
      { requestRender: () => {} },
      { fg: (_token: string, text: string) => text },
      { onBranchChange: () => () => {}, getGitBranch: () => null },
    );
    expect(footer).toBeDefined();
    return {
      footer,
      setStale: (value: boolean) => {
        stale = value;
      },
    };
  };

  test("renders generic registered footer contributions", async () => {
    const entries = [{ type: "custom", customType: "x" }];
    const { footer } = await createHarness(false, entries);
    registerFooterContribution({
      id: "test-badge",
      render: ({ entries: contributionEntries }, theme) =>
        contributionEntries === entries
          ? theme.fg("success", "badge")
          : undefined,
    });
    expect(footer.render(80)[0]).toContain("badge");
    footer.dispose();
    clearFooterContributionsForTests();
  });

  test("reuses last good line on stale-extension error", async () => {
    const { footer, setStale } = await createHarness(false);
    const first = footer.render(80)[0];
    setStale(true);
    const second = footer.render(80)[0];
    expect(second).toBe(first);
    footer.dispose();
  });

  test("renders cwd-only line when stale before first successful render", async () => {
    const { footer } = await createHarness(true);
    const line = footer.render(80)[0] ?? "";
    expect(line).toContain("/tmp");
    expect(line.toLowerCase()).not.toContain("reloading");
    footer.dispose();
  });
});
