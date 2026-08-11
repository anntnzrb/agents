import { describe, expect, test } from "bun:test";
import { __test } from "./index.js";

describe("turn-stats helpers", () => {
  test("summarizes assistant token usage", () => {
    expect(
      __test.summarizeTurnUsage([
        { role: "user", usage: { input: 999, output: 999 } },
        { role: "assistant", usage: { input: 10, output: 5 } },
        { role: "assistant", usage: { inputTokens: 7, outputTokens: 3 } },
      ]),
    ).toEqual({ input: 17, output: 8 });
  });

  test("summarizes context-gc index entries as gc events and estimated tokens", () => {
    const entries = [
      {
        type: "custom",
        customType: "context-gc-index",
        data: {
          records: [
            { toolCallId: "a", resultText: "12345" },
            { toolCallId: "b", resultText: "123" },
          ],
        },
      },
      {
        type: "custom",
        customType: "context-gc-index",
        data: { records: [{ toolCallId: "c", resultText: "1234" }] },
      },
    ];

    expect(__test.summarizeGcStats(entries)).toEqual({
      events: 2,
      estimatedTokens: 3,
    });
  });

  test("appends broom stats as gc-event count plus estimated tokens", () => {
    expect(__test.formatGcStats({ events: 0, estimatedTokens: 0 })).toBe("");
    expect(__test.formatGcStats({ events: 12, estimatedTokens: 53_000 })).toBe(
      " · 🧹 12 ~53kt",
    );
    expect(
      __test.formatTurnStats({ input: 1000, output: 50 }, 1000, {
        events: 12,
        estimatedTokens: 53_000,
      }),
    ).toContain("🧹 12 ~53kt");
  });
});
