import { describe, expect, it } from "bun:test";
import {
  contentUsage,
  parseContentArgs,
  parseSearchArgs,
  searchUsage,
} from "@/args";

describe("parseSearchArgs", () => {
  it("parses query and defaults", () => {
    const result = parseSearchArgs(["hello", "world"]);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.query).toBe("hello world");
      expect(result.value.numResults).toBe(5);
      expect(result.value.fetchContent).toBe(false);
    }
  });

  it("parses -n and --content", () => {
    const result = parseSearchArgs(["-n", "3", "--content", "rust"]);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.numResults).toBe(3);
      expect(result.value.fetchContent).toBe(true);
      expect(result.value.query).toBe("rust");
    }
  });

  it("rejects missing query", () => {
    const result = parseSearchArgs([]);
    expect(result.ok).toBe(false);
  });

  it("rejects invalid -n", () => {
    const result = parseSearchArgs(["-n", "0", "query"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing -n value", () => {
    const result = parseSearchArgs(["-n"]);
    expect(result.ok).toBe(false);
  });
});

describe("parseContentArgs", () => {
  it("parses url", () => {
    const result = parseContentArgs(["https://example.com"]);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.url).toBe("https://example.com");
    }
  });

  it("rejects missing url", () => {
    const result = parseContentArgs([]);
    expect(result.ok).toBe(false);
  });
});

describe("usage helpers", () => {
  it("returns search usage text", () => {
    expect(typeof searchUsage()).toBe("string");
    expect(searchUsage()).toContain("Usage: search.ts");
  });

  it("returns content usage text", () => {
    expect(typeof contentUsage()).toBe("string");
    expect(contentUsage()).toContain("Usage: content.ts");
  });
});
