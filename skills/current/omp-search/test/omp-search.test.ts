import { describe, expect, it } from "bun:test";
import { BunServices } from "@effect/platform-bun";
import { Effect } from "effect";
import { Command } from "effect/unstable/cli";
import { discoverActiveOmpProviders, extractYamlList } from "#config";
import { failureMessage, resolveOmp } from "#executor";
import { mergeParallelResults } from "#merge";
import type { SearchFailurePayload, SearchSuccessPayload } from "#models";
import {
  frameContent,
  parseSearchOutput,
  redact,
  stripTerminalControls,
} from "#parser";
import { searchCommand } from "../scripts/cli.ts";

describe("parser", () => {
  it("strips ANSI and OSC terminal controls and normalizes newlines", () => {
    const raw = "\x1b[31mError\x1b[0m\x1b]0;Title\x07\r\nLine 2\rLine 3";
    const cleaned = stripTerminalControls(raw);
    expect(cleaned).toBe("Error\nLine 2\nLine 3");
  });

  it("redacts sensitive keys, tokens, and bearer auth", () => {
    const text =
      "sk-abcdef1234567890\nOPENAI_API_KEY=sk-xyz1234567890\nAuthorization: Bearer secret-token-value";
    const redacted = redact(text);
    expect(redacted).toContain("<redacted>");
    expect(redacted).not.toContain("sk-abcdef1234567890");
    expect(redacted).not.toContain("secret-token-value");
  });

  it("strips box-drawing frames correctly", () => {
    expect(frameContent("│  hello world  │")).toBe("  hello world");
    expect(frameContent("│  hello world")).toBe("  hello world");
    expect(frameContent("hello world")).toBe("hello world");
  });

  it("parses structured search output with answer and sources", () => {
    const raw = `
Web Search: Brave 2 sources
--- Answer ---
Here is the summary of results.
--- Sources ---
+ Bun 1.2 Release Notes (bun.sh)
- TypeScript Documentation (www.typescriptlang.org; 2 days ago)
--- Metadata ---
Provider: Brave
query: latest Bun release
----------------
`;
    const parsed = parseSearchOutput(raw, "fallback query");
    expect(parsed.provider).toBe("Brave");
    expect(parsed.query).toBe("latest Bun release");
    expect(parsed.answer).toBe("Here is the summary of results.");
    expect(parsed.sources.length).toBe(2);
    expect(parsed.sources[0]).toEqual({
      title: "Bun 1.2 Release Notes",
      domain: "bun.sh",
      age: null,
    });
    expect(parsed.sources[1]).toEqual({
      title: "TypeScript Documentation",
      domain: "www.typescriptlang.org",
      age: "2 days ago",
    });
    expect(parsed.truncated).toBe(false);
    expect(parsed.parsed).toBe(true);
  });

  it("parses Unicode box-drawing outputs from live OMP CLI", () => {
    const raw = `
╭─── ⌕ Web Search: Brave 2 sources ──────────────────────────────────────────────╮
│ Query: test query                                                              │
├─── Answer ─────────────────────────────────────────────────────────────────────┤
│ Answer text goes here.                                                         │
├─── Sources ────────────────────────────────────────────────────────────────────┤
│ ├─ Test Source (test.com) · 1 week ago                                         │
│ └─ Second Source (other.org) · 3 days ago                                      │
├─── Metadata ───────────────────────────────────────────────────────────────────┤
│ Provider: Brave (API)                                                          │
╰────────────────────────────────────────────────────────────────────────────────╯
`;
    const parsed = parseSearchOutput(raw, "fallback");
    expect(parsed.provider).toBe("Brave (API)");
    expect(parsed.query).toBe("test query");
    expect(parsed.answer).toBe(" Answer text goes here.");
    expect(parsed.sources.length).toBe(2);
    expect(parsed.sources[0]).toEqual({
      title: "Test Source",
      domain: "test.com",
      age: "1 week ago",
    });
    expect(parsed.sources[1]).toEqual({
      title: "Second Source",
      domain: "other.org",
      age: "3 days ago",
    });
  });

  it("detects truncation marker in search output", () => {
    const raw = `
Web Search: Exa 1 source
--- Answer ---
Short answer
... 12 more lines
--- Sources ---
+ Source 1 (example.com)
`;
    const parsed = parseSearchOutput(raw, "query");
    expect(parsed.truncated).toBe(true);
  });
});

describe("config", () => {
  it("extracts YAML list under providers section", () => {
    const yaml = `
providers:
  webSearchOrder:
    - brave # fast search
    - parallel
    - exa
  webSearchExclude:
    - gemini
`;
    const order = extractYamlList(yaml, "webSearchOrder");
    const exclude = extractYamlList(yaml, "webSearchExclude");
    expect(order).toEqual(["brave", "parallel", "exa"]);
    expect(exclude).toEqual(["gemini"]);
  });

  it("ignores items outside the target key", () => {
    const yaml = `
otherSection:
  webSearchOrder:
    - should_ignore
providers:
  otherKey:
    - other_val
  webSearchOrder:
    - brave
`;
    const order = extractYamlList(yaml, "webSearchOrder");
    expect(order).toEqual(["brave"]);
  });

  it("discovers active providers with discoverActiveOmpProviders Effect", async () => {
    const providers = await Effect.runPromise(
      discoverActiveOmpProviders().pipe(Effect.provide(BunServices.layer))
    );
    expect(Array.isArray(providers)).toBe(true);
  });
});

describe("executor helpers", () => {
  it("extracts failure messages from stderr or stdout", () => {
    expect(failureMessage("stdout line", "Error: failed to connect", 1)).toBe(
      "Error: failed to connect"
    );
    expect(failureMessage("cleaned output\nsomething went wrong", "", 1)).toBe(
      "something went wrong"
    );
    expect(failureMessage("", "", 2)).toBe("omp search exited with code 2");
  });

  it("resolves omp binary path if exists", async () => {
    const resolved = await Effect.runPromise(
      resolveOmp(process.execPath).pipe(Effect.provide(BunServices.layer))
    );
    expect(resolved).toBe(process.execPath);
  });
});

describe("mergeParallelResults", () => {
  it("merges multiple successful results and deduplicates sources", () => {
    const result1: SearchSuccessPayload = {
      ok: true,
      query: "test query",
      provider: "brave",
      providers: ["brave"],
      providers_count: 1,
      answer: "Brave answer summary.",
      sources: [
        { title: "Doc 1", domain: "example.com", age: null },
        { title: "Doc 2", domain: "test.org", age: "1d ago" },
      ],
      sources_count: 2,
      truncated: false,
      compact: true,
      parsed: true,
      exit_code: 0,
    };

    const result2: SearchSuccessPayload = {
      ok: true,
      query: "test query",
      provider: "exa",
      providers: ["exa"],
      providers_count: 1,
      answer: "Exa detailed answer.",
      sources: [
        { title: "Doc 1", domain: "EXAMPLE.COM", age: null }, // Duplicate
        { title: "Doc 3", domain: "other.com", age: "3d ago" },
      ],
      sources_count: 2,
      truncated: true,
      compact: true,
      parsed: true,
      exit_code: 0,
    };

    const merged = mergeParallelResults("test query", [result1, result2], true);
    expect(merged.ok).toBe(true);
    if (merged.ok) {
      expect(merged.provider).toBe("brave+exa");
      expect(merged.providers).toEqual(["brave", "exa"]);
      expect(merged.providers_count).toBe(2);
      expect(merged.answer).toContain("### [brave]\nBrave answer summary.");
      expect(merged.answer).toContain("### [exa]\nExa detailed answer.");
      expect(merged.sources.length).toBe(3);
      expect(merged.sources_count).toBe(3);
      expect(merged.truncated).toBe(true);
      expect(merged.compact).toBe(true);
    }
  });

  it("handles all-failed provider results gracefully", () => {
    const failed1: SearchFailurePayload = {
      ok: false,
      query: "test query",
      provider: "brave",
      answer: "",
      sources: [],
      truncated: false,
      compact: true,
      parsed: false,
      exit_code: 1,
      error: { code: "provider_error", message: "Brave rate limit" },
    };
    const failed2: SearchFailurePayload = {
      ok: false,
      query: "test query",
      provider: "exa",
      answer: "",
      sources: [],
      truncated: false,
      compact: true,
      parsed: false,
      exit_code: 1,
      error: { code: "provider_error", message: "Exa timeout" },
    };

    const merged = mergeParallelResults("test query", [failed1, failed2], true);
    expect(merged.ok).toBe(false);
    if (!merged.ok) {
      expect(merged.exit_code).toBe(1);
      expect(merged.error.message).toBe("Brave rate limit");
      expect(merged.provider).toBe("brave | exa");
    }
  });
});

describe("effect/unstable/cli Command execution", () => {
  it("renders help documentation when given --help", async () => {
    const runner = Command.runWith(searchCommand, { version: "1.0.0" });
    await Effect.runPromise(
      runner(["--help"]).pipe(Effect.provide(BunServices.layer))
    );
  });
});
