import { describe, expect, it } from "bun:test";
import type {
  ContentsOptions,
  RegularSearchOptions,
  Research,
  ResearchCreateRequest,
  SearchResult,
} from "exa-js";
import { createExaClient } from "@/client";
import { McpToolUnavailableError } from "@/mcp";

type FakeExaInstance = {
  apiKey: string;
  lastSearch?: { query: string; options?: RegularSearchOptions };
  lastContents?: {
    urls: string[] | string | SearchResult<ContentsOptions>[];
    options?: ContentsOptions;
  };
  lastAnswer?: { query: string; options?: unknown };
  lastResearchCreate?: { instructions: string };
  lastResearchGet?: {
    id: string;
    options?: { stream?: false; events?: boolean };
  };
};

class FakeExa {
  apiKey: string;
  lastSearch?: { query: string; options?: RegularSearchOptions };
  lastContents?: {
    urls: string[] | string | SearchResult<ContentsOptions>[];
    options?: ContentsOptions;
  };
  lastAnswer?: { query: string; options?: unknown };
  lastResearchCreate?: { instructions: string };
  lastResearchGet?: {
    id: string;
    options?: { stream?: false; events?: boolean };
  };

  constructor(apiKey: string) {
    this.apiKey = apiKey;
    lastInstance = this;
  }

  search(query: string, options?: RegularSearchOptions) {
    this.lastSearch = options ? { query, options } : { query };
    return Promise.resolve({ requestId: "req", results: [] });
  }

  getContents(
    urls: string[] | string | SearchResult<ContentsOptions>[],
    options?: ContentsOptions,
  ) {
    this.lastContents = options ? { urls, options } : { urls };
    return Promise.resolve({ requestId: "req", results: [] });
  }

  answer(query: string, options?: unknown) {
    this.lastAnswer = { query, options };
    return Promise.resolve({ answer: "ok", citations: [] });
  }

  research = {
    create: (params: { instructions: string }) => {
      this.lastResearchCreate = params;
      return Promise.resolve({
        researchId: "r1",
        instructions: params.instructions,
        createdAt: 0,
        status: "completed",
      } as Research);
    },
    get: (id: string, options?: { stream?: false; events?: boolean }) => {
      this.lastResearchGet = options ? { id, options } : { id };
      return Promise.resolve({
        researchId: id,
        instructions: "",
        createdAt: 0,
        status: "completed",
      } as Research);
    },
  };
}

let lastInstance: FakeExaInstance | null = null;

function requireLastInstance(): FakeExaInstance {
  if (!lastInstance) {
    throw new Error("Expected Exa instance to be created.");
  }
  return lastInstance as FakeExaInstance;
}

describe("createExaClient", () => {
  it("proxies answer to Exa SDK", async () => {
    lastInstance = null;
    const client = createExaClient("key", FakeExa);

    await client.answer("question", { text: true });

    const instance = requireLastInstance();

    expect(instance.apiKey).toBe("key");
    expect(instance.lastAnswer?.query).toBe("question");
  });

  it("routes search, contents, and research to MCP only", async () => {
    lastInstance = null;
    const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async (_config, name, args) => {
        calls.push({ name, args });
        return { content: [{ type: "text", text: "mcp" }] };
      },
    });

    await client.search("query", { numResults: 1, type: "fast" });
    await client.getContents("https://example.com", { text: true });
    await client.research.create({
      instructions: "do it",
      model: "exa-research",
    });
    await client.research.get("task");

    const instance = requireLastInstance();
    expect(instance.lastSearch).toBeUndefined();
    expect(instance.lastContents).toBeUndefined();
    expect(instance.lastResearchCreate).toBeUndefined();
    expect(instance.lastResearchGet).toBeUndefined();
    expect(calls.map((call) => call.name)).toEqual([
      "web_search_exa",
      "crawling_exa",
      "deep_researcher_start",
      "deep_researcher_check",
    ]);
  });

  it("uses MCP for compatible search", async () => {
    const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async (_config, name, args) => {
        calls.push({ name, args });
        return { content: [{ type: "text", text: "mcp" }] };
      },
    });

    const result = await client.search("query", {
      numResults: 1,
      type: "fast",
    });
    expect(result.kind).toBe("text");
    expect(calls[0]?.name).toBe("web_search_exa");
  });

  it("uses MCP for search without options", async () => {
    const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async (_config, name, args) => {
        calls.push({ name, args });
        return { content: [{ type: "text", text: "mcp" }] };
      },
    });

    await client.search("query");
    expect(calls[0]?.args).toEqual({ query: "query" });
  });

  it("uses MCP for search without type", async () => {
    const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async (_config, name, args) => {
        calls.push({ name, args });
        return { content: [{ type: "text", text: "mcp" }] };
      },
    });

    await client.search("query", { numResults: 1 });
    expect(calls[0]?.args).toEqual({ query: "query", numResults: 1 });
  });

  it("throws when MCP tool unavailable", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async () => {
        throw new McpToolUnavailableError("web_search_exa");
      },
    });

    await expect(
      client.search("query", { numResults: 1, type: "fast" }),
    ).rejects.toBeInstanceOf(McpToolUnavailableError);
  });

  it("returns MCP text for research check", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async () => ({ content: [{ type: "text", text: "done" }] }),
    });

    const result = await client.research.get("task");
    expect(result.kind).toBe("text");
  });

  it("throws for research check events option", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async () => ({ content: [{ type: "text", text: "done" }] }),
    });

    await expect(
      client.research.get("task", { events: true }),
    ).rejects.toBeInstanceOf(Error);
  });

  it("uses MCP for contents when compatible", async () => {
    const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async (_config, name, args) => {
        calls.push({ name, args });
        return { content: [{ type: "text", text: "ok" }] };
      },
    });

    const result = await client.getContents("https://example.com", {
      text: { maxCharacters: 1200 },
    });
    expect(result.kind).toBe("text");
    expect(calls[0]?.name).toBe("crawling_exa");
  });

  it("throws when contents includes multiple URLs", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async () => ({ content: [{ type: "text", text: "ok" }] }),
    });

    await expect(
      client.getContents(["https://example.com", "https://example.org"]),
    ).rejects.toBeInstanceOf(Error);
  });

  it("uses MCP for research start when compatible", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async () => ({ content: [{ type: "text", text: "started" }] }),
    });

    const result = await client.research.create({
      instructions: "do it",
      model: "exa-research",
    });
    expect(result.kind).toBe("text");
  });

  it("throws for research start with unsupported model", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpCaller: async () => ({ content: [{ type: "text", text: "ok" }] }),
    });

    await expect(
      client.research.create({
        instructions: "do it",
        model: "exa-research-fast" as ResearchCreateRequest["model"],
      }),
    ).rejects.toBeInstanceOf(Error);
  });

  it("uses MCP for deep search and code context", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async () => ({ content: [{ type: "text", text: "ok" }] }),
    });

    const deep = await client.deepSearch("objective", ["a", "b"]);
    const code = await client.codeContext("query", 2000);
    const company = await client.companyResearch("Acme", 2);
    const linkedin = await client.linkedinSearch("Jane", "profiles", 2);
    expect(deep.kind).toBe("text");
    expect(code.kind).toBe("text");
    expect(company.kind).toBe("text");
    expect(linkedin.kind).toBe("text");
  });

  it("throws on MCP tool error", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async () => ({
        content: [{ type: "text", text: "boom" }],
        isError: true,
      }),
    });

    await expect(client.codeContext("query")).rejects.toBeInstanceOf(Error);
  });

  it("propagates unexpected MCP errors", async () => {
    const client = createExaClient("key", FakeExa, {
      mcpConfig: { url: "https://mcp.exa.ai/mcp" },
      mcpCaller: async () => {
        throw new Error("network");
      },
    });

    await expect(
      client.search("query", { numResults: 1, type: "fast" }),
    ).rejects.toBeInstanceOf(Error);
  });
});
