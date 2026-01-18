import { describe, expect, it } from "bun:test";
import type {
  CallToolResult,
  ContentBlock,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import {
  callMcpTool,
  createMcpConnection,
  formatMcpToolResult,
  McpToolUnavailableError,
  resolveMcpConfig,
  type McpConnectionFactory,
} from "@/mcp";

const baseResult: CallToolResult = {
  content: [{ type: "text", text: "ok" }],
};

function hasContent(
  result: CallToolResult | { toolResult: unknown },
): result is CallToolResult {
  return "content" in result;
}

describe("resolveMcpConfig", () => {
  it("uses default url and tools", () => {
    const config = resolveMcpConfig({}, "key");
    expect(config.url).toContain("https://mcp.exa.ai/mcp");
    expect(config.url).toContain("exaApiKey=key");
    expect(config.url).toContain("tools=");
    expect(config.url).toContain("web_search_exa");
  });

  it("respects explicit url and tools", () => {
    const config = resolveMcpConfig(
      {
        EXA_MCP_URL: "https://mcp.exa.ai/mcp?exaApiKey=abc",
        EXA_MCP_TOOLS: "web_search_exa",
      },
      "key",
    );
    expect(config?.url).toContain("exaApiKey=abc");
    expect(config?.url).toContain("tools=web_search_exa");
  });
});

describe("formatMcpToolResult", () => {
  it("formats structured content", () => {
    const output = formatMcpToolResult({
      content: [],
      structuredContent: { value: 1 },
    });
    expect(output).toContain('"value": 1');
  });

  it("formats toolResult fallback", () => {
    const output = formatMcpToolResult({
      toolResult: { ok: true },
    });
    expect(output).toContain('"ok": true');
  });

  it("formats content blocks", () => {
    const blocks: ContentBlock[] = [
      { type: "text", text: "hello" },
      { type: "resource_link", uri: "exa://doc", name: "doc" },
      { type: "resource", resource: { uri: "exa://txt", text: "doc" } },
      { type: "resource", resource: { uri: "exa://bin", blob: "AA==" } },
      { type: "image", data: "", mimeType: "image/png" },
      { type: "audio", data: "", mimeType: "audio/mpeg" },
      { type: "unknown" } as unknown as ContentBlock,
    ];
    const output = formatMcpToolResult({ content: blocks });
    expect(output).toContain("hello");
    expect(output).toContain("Resource: exa://doc");
    expect(output).toContain("doc");
    expect(output).toContain("Resource: exa://bin");
    expect(output).toContain("[image]");
    expect(output).toContain("[audio]");
  });
});

describe("callMcpTool", () => {
  it("calls tool and closes connection", async () => {
    let closed = false;
    let called = false;
    const tools: Tool[] = [
      {
        name: "web_search_exa",
        description: "",
        inputSchema: { type: "object" },
      },
    ];
    const factory: McpConnectionFactory = async () => ({
      listTools: async () => tools,
      callTool: async () => {
        called = true;
        return baseResult;
      },
      close: async () => {
        closed = true;
      },
    });

    const result = await callMcpTool(
      { url: "https://mcp.exa.ai/mcp" },
      "web_search_exa",
      { query: "test" },
      factory,
    );
    expect(called).toBe(true);
    expect(closed).toBe(true);
    if (hasContent(result)) {
      expect(result.content[0]?.type).toBe("text");
    } else {
      throw new Error("Expected content result.");
    }
  });

  it("throws when tool missing", async () => {
    let closed = false;
    const factory: McpConnectionFactory = async () => ({
      listTools: async () => [],
      callTool: async () => baseResult,
      close: async () => {
        closed = true;
      },
    });

    await expect(
      callMcpTool({ url: "https://mcp.exa.ai/mcp" }, "missing", {}, factory),
    ).rejects.toBeInstanceOf(McpToolUnavailableError);
    expect(closed).toBe(true);
  });

  it("creates MCP connection with injected deps", async () => {
    let connected = false;
    let closed = false;
    const tools: Tool[] = [
      {
        name: "web_search_exa",
        description: "",
        inputSchema: { type: "object" },
      },
    ];

    class FakeTransport {
      sessionId?: string;
      constructor(_url: URL) {}
      start(): Promise<void> {
        return Promise.resolve();
      }
      send(): Promise<void> {
        return Promise.resolve();
      }
      close(): Promise<void> {
        return Promise.resolve();
      }
    }

    class FakeClient {
      constructor(_info: { name: string; version: string }) {}
      connect(): Promise<void> {
        connected = true;
        return Promise.resolve();
      }
      listTools(): Promise<{ tools: Tool[] }> {
        return Promise.resolve({ tools });
      }
      callTool(): Promise<CallToolResult> {
        return Promise.resolve(baseResult);
      }
      close(): Promise<void> {
        closed = true;
        return Promise.resolve();
      }
    }

    const connection = await createMcpConnection(
      { url: "https://mcp.exa.ai/mcp" },
      {
        clientCtor: FakeClient as unknown as new (
          info: { name: string; version: string },
          options: { capabilities: Record<string, never> },
        ) => {
          connect: (transport: unknown) => Promise<void>;
          listTools: () => Promise<{ tools: Tool[] }>;
          callTool: (params: {
            name: string;
            arguments: Record<string, unknown>;
          }) => Promise<CallToolResult>;
          close: () => Promise<void>;
        },
        transportCtor: FakeTransport as unknown as new (url: URL) => {
          start: () => Promise<void>;
          send: () => Promise<void>;
          close: () => Promise<void>;
          sessionId?: string;
        },
      },
    );

    const listed = await connection.listTools();
    await connection.callTool("web_search_exa", {});
    await connection.close();

    expect(connected).toBe(true);
    expect(closed).toBe(true);
    expect(listed[0]?.name).toBe("web_search_exa");
  });
});
