import { describe, expect, it } from "bun:test";
import { parseCommand, usage } from "@/args";

const schemaJson = JSON.stringify({
  type: "object",
  properties: { answer: { type: "string" } },
});

describe("parseCommand", () => {
  it("parses search with options", () => {
    const result = parseCommand([
      "search",
      "deep",
      "query",
      "-n",
      "3",
      "--type",
      "deep",
      "--text-max",
      "2000",
    ]);

    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "search") {
      expect(result.value.query).toBe("deep query");
      expect(result.value.options.numResults).toBe(3);
      expect(result.value.options.type).toBe("deep");
      if (result.value.options.contents?.text) {
        if (typeof result.value.options.contents.text === "object") {
          expect(result.value.options.contents.text.maxCharacters).toBe(2000);
        } else {
          throw new Error("Expected text contents options.");
        }
      } else {
        throw new Error("Expected contents options.");
      }
    }
  });

  it("rejects missing query", () => {
    const result = parseCommand(["search", "-n", "2"]);
    expect(result.ok).toBe(false);
  });

  it("rejects invalid search type", () => {
    const result = parseCommand(["search", "query", "--type", "weird"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing -n value", () => {
    const result = parseCommand(["search", "query", "-n"]);
    expect(result.ok).toBe(false);
  });

  it("rejects invalid -n value", () => {
    const result = parseCommand(["search", "query", "-n", "0"]);
    expect(result.ok).toBe(false);
  });

  it("rejects unknown search option", () => {
    const result = parseCommand(["search", "query", "--bogus"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing text-max value", () => {
    const result = parseCommand(["search", "query", "--text-max"]);
    expect(result.ok).toBe(false);
  });

  it("skips empty search args", () => {
    const result = parseCommand(["search", "", "query"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "search") {
      expect(result.value.query).toBe("query");
    }
  });

  it("parses contents with flags", () => {
    const result = parseCommand([
      "contents",
      "https://example.com",
      "https://example.org",
      "--text-max",
      "1500",
    ]);

    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "contents") {
      expect(result.value.urls.length).toBe(2);
      expect(
        result.value.options.text &&
          typeof result.value.options.text === "object",
      ).toBe(true);
    }
  });

  it("defaults contents text for contents command", () => {
    const result = parseCommand(["contents", "https://example.com"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "contents") {
      expect(result.value.options.text).toBeDefined();
    }
  });

  it("skips empty contents args", () => {
    const result = parseCommand(["contents", "", "https://example.com"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "contents") {
      expect(result.value.urls.length).toBe(1);
    }
  });

  it("rejects missing contents urls", () => {
    const result = parseCommand(["contents"]);
    expect(result.ok).toBe(false);
  });

  it("rejects unknown contents option", () => {
    const result = parseCommand(["contents", "https://example.com", "--nope"]);
    expect(result.ok).toBe(false);
  });

  it("parses answer with schema", () => {
    const result = parseCommand([
      "answer",
      "What",
      "now",
      "--text",
      "--system",
      "be precise",
      "--schema",
      schemaJson,
    ]);

    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "answer") {
      expect(result.value.query).toBe("What now");
      expect(result.value.options.text).toBe(true);
      expect(result.value.options.systemPrompt).toBe("be precise");
      expect(result.value.options.outputSchema).toBeDefined();
    }
  });

  it("rejects invalid schema", () => {
    const result = parseCommand(["answer", "question", "--schema", "[]"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing schema value", () => {
    const result = parseCommand(["answer", "question", "--schema"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing answer question", () => {
    const result = parseCommand(["answer", "--text"]);
    expect(result.ok).toBe(false);
  });

  it("rejects unsupported answer model", () => {
    const result = parseCommand(["answer", "question", "--model", "exa-pro"]);
    expect(result.ok).toBe(false);
  });

  it("parses answer model exa", () => {
    const result = parseCommand(["answer", "question", "--model", "exa"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "answer") {
      expect(result.value.options.model).toBe("exa");
    }
  });

  it("rejects unknown answer option", () => {
    const result = parseCommand(["answer", "question", "--bogus"]);
    expect(result.ok).toBe(false);
  });

  it("skips empty answer args", () => {
    const result = parseCommand(["answer", "", "question"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "answer") {
      expect(result.value.query).toBe("question");
    }
  });

  it("parses research start", () => {
    const result = parseCommand([
      "research-start",
      "Do",
      "the",
      "thing",
      "--model",
      "exa-research",
    ]);

    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "research-start") {
      expect(result.value.instructions).toBe("Do the thing");
      expect(result.value.options.model).toBe("exa-research");
    }
  });

  it("rejects missing research instructions", () => {
    const result = parseCommand(["research-start", "--model", "exa-research"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing model value", () => {
    const result = parseCommand(["research-start", "do", "--model"]);
    expect(result.ok).toBe(false);
  });

  it("rejects unsupported research model", () => {
    const result = parseCommand([
      "research-start",
      "do",
      "--model",
      "exa-research-fast",
    ]);
    expect(result.ok).toBe(false);
  });

  it("rejects unknown research-start option", () => {
    const result = parseCommand(["research-start", "do", "--bad"]);
    expect(result.ok).toBe(false);
  });

  it("skips empty research-start args", () => {
    const result = parseCommand(["research-start", "", "do", "work"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "research-start") {
      expect(result.value.instructions).toBe("do work");
    }
  });

  it("parses research check", () => {
    const result = parseCommand(["research-check", "task-123"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "research-check") {
      expect(result.value.id).toBe("task-123");
    }
  });

  it("parses deep search", () => {
    const result = parseCommand([
      "deep-search",
      "Find",
      "pricing",
      "--queries",
      "pricing,plans",
    ]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "deep-search") {
      expect(result.value.objective).toBe("Find pricing");
      expect(result.value.queries?.length).toBe(2);
    }
  });

  it("rejects missing deep search objective", () => {
    const result = parseCommand(["deep-search", "--queries", "a,b"]);
    expect(result.ok).toBe(false);
  });

  it("rejects unknown deep search option", () => {
    const result = parseCommand(["deep-search", "topic", "--bad"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing deep search queries value", () => {
    const result = parseCommand(["deep-search", "topic", "--queries"]);
    expect(result.ok).toBe(false);
  });

  it("rejects empty deep search queries", () => {
    const result = parseCommand(["deep-search", "topic", "--queries", ","]);
    expect(result.ok).toBe(false);
  });

  it("skips empty deep search args", () => {
    const result = parseCommand(["deep-search", "", "topic"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "deep-search") {
      expect(result.value.objective).toBe("topic");
    }
  });

  it("parses code context", () => {
    const result = parseCommand([
      "code-context",
      "React",
      "hooks",
      "--tokens",
      "2000",
    ]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "code-context") {
      expect(result.value.query).toBe("React hooks");
      expect(result.value.tokensNum).toBe(2000);
    }
  });

  it("defaults code context tokens", () => {
    const result = parseCommand(["code-context", "React", "hooks"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "code-context") {
      expect(result.value.tokensNum).toBe(50000);
    }
  });

  it("rejects unknown code context option", () => {
    const result = parseCommand(["code-context", "query", "--bad"]);
    expect(result.ok).toBe(false);
  });

  it("skips empty code context args", () => {
    const result = parseCommand(["code-context", "", "query"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "code-context") {
      expect(result.value.query).toBe("query");
    }
  });

  it("rejects code context tokens out of range", () => {
    const result = parseCommand(["code-context", "query", "--tokens", "10"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing code context query", () => {
    const result = parseCommand(["code-context", "--tokens", "2000"]);
    expect(result.ok).toBe(false);
  });

  it("parses company research", () => {
    const result = parseCommand(["company-research", "Acme", "-n", "4"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "company-research") {
      expect(result.value.companyName).toBe("Acme");
      expect(result.value.numResults).toBe(4);
    }
  });

  it("rejects unknown company research option", () => {
    const result = parseCommand(["company-research", "Acme", "--bad"]);
    expect(result.ok).toBe(false);
  });

  it("skips empty company research args", () => {
    const result = parseCommand(["company-research", "", "Acme"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "company-research") {
      expect(result.value.companyName).toBe("Acme");
    }
  });

  it("rejects missing company name", () => {
    const result = parseCommand(["company-research", "-n", "3"]);
    expect(result.ok).toBe(false);
  });

  it("parses linkedin search", () => {
    const result = parseCommand([
      "linkedin-search",
      "Jane",
      "Doe",
      "--type",
      "profiles",
      "-n",
      "2",
    ]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "linkedin-search") {
      expect(result.value.query).toBe("Jane Doe");
      expect(result.value.searchType).toBe("profiles");
      expect(result.value.numResults).toBe(2);
    }
  });

  it("rejects unknown linkedin option", () => {
    const result = parseCommand(["linkedin-search", "Jane", "--bad"]);
    expect(result.ok).toBe(false);
  });

  it("skips empty linkedin args", () => {
    const result = parseCommand(["linkedin-search", "", "Jane"]);
    expect(result.ok).toBe(true);
    if (result.ok && result.value.kind === "linkedin-search") {
      expect(result.value.query).toBe("Jane");
    }
  });

  it("rejects invalid linkedin type", () => {
    const result = parseCommand([
      "linkedin-search",
      "Jane",
      "--type",
      "unknown",
    ]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing linkedin query", () => {
    const result = parseCommand(["linkedin-search", "--type", "all"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing research check id", () => {
    const result = parseCommand(["research-check"]);
    expect(result.ok).toBe(false);
  });

  it("rejects extra args for research check", () => {
    const result = parseCommand(["research-check", "task-123", "extra"]);
    expect(result.ok).toBe(false);
  });

  it("handles help flag", () => {
    const result = parseCommand(["search", "--help"]);
    expect(result.ok).toBe(false);
  });

  it("rejects missing command", () => {
    const result = parseCommand([]);
    expect(result.ok).toBe(false);
  });

  it("rejects unknown command", () => {
    const result = parseCommand(["unknown"]);
    expect(result.ok).toBe(false);
  });

  it("returns usage text", () => {
    expect(usage()).toContain("exa.ts search");
    expect(usage()).toContain("exa.ts deep-search");
  });
});
