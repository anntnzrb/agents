import { describe, expect, test } from "bun:test";
import { findBuiltinMetadata, type BuiltinMetadataEntry } from "./metadata.ts";

const maxMap = {
  off: null,
  minimal: "minimal",
  low: "low",
  medium: "medium",
  high: "high",
  xhigh: "xhigh",
  max: "max",
} as const;

const entry = (
  provider: string,
  thinkingLevelMap: Record<string, string | null>,
): BuiltinMetadataEntry => ({
  provider,
  metadata: { thinkingLevelMap: { ...thinkingLevelMap } },
});

describe("findBuiltinMetadata", () => {
  test("resolves through leading pool segments", () => {
    const index = new Map<string, BuiltinMetadataEntry[]>([
      ["meta/muse-spark-1.3-contributor", [entry("openrouter", { ...maxMap })]],
    ]);
    const resolved = findBuiltinMetadata(index, "command-code/meta/muse-spark-1.3-contributor");
    expect(resolved?.thinkingLevelMap?.max).toBe("max");
  });

  test("prefers the provider named in the gateway id", () => {
    const index = new Map<string, BuiltinMetadataEntry[]>([
      [
        "deepseek-v4-pro",
        [entry("other", { max: null }), entry("opencode-go", { max: "max" })],
      ],
    ]);
    const resolved = findBuiltinMetadata(index, "opencode-go/deepseek-v4-pro");
    expect(resolved?.thinkingLevelMap?.max).toBe("max");
  });

  test("returns undefined when no suffix matches", () => {
    const index = new Map<string, BuiltinMetadataEntry[]>([
      ["deepseek-v4-flash", [entry("deepseek", { max: "max" })]],
    ]);
    expect(findBuiltinMetadata(index, "command-code/deepseek/deepseek-v4.1-flash")).toBeUndefined();
  });
});
