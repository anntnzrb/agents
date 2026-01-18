import { Client } from "@modelcontextprotocol/sdk/client";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type {
  CallToolResult,
  CompatibilityCallToolResult,
  ContentBlock,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";

export type McpConfig = {
  url: string;
};

export type McpToolResult = CallToolResult | CompatibilityCallToolResult;

export type McpConnection = {
  listTools: () => Promise<Tool[]>;
  callTool: (
    name: string,
    args: Record<string, unknown>,
  ) => Promise<McpToolResult>;
  close: () => Promise<void>;
};

export type McpConnectionFactory = (
  config: McpConfig,
) => Promise<McpConnection>;

type ClientLike = {
  connect: (transport: Transport) => Promise<void>;
  listTools: () => Promise<{ tools: Tool[] }>;
  callTool: (params: {
    name: string;
    arguments: Record<string, unknown>;
  }) => Promise<McpToolResult>;
  close: () => Promise<void>;
};

type ClientConstructor = new (
  info: { name: string; version: string },
  options: { capabilities: Record<string, never> },
) => ClientLike;

type TransportConstructor = new (url: URL) => Transport;

export class McpToolUnavailableError extends Error {
  constructor(toolName: string) {
    super(`MCP tool unavailable: ${toolName}`);
  }
}

const DEFAULT_MCP_URL = "https://mcp.exa.ai/mcp";
const DEFAULT_MCP_TOOLS =
  "web_search_exa,deep_search_exa,get_code_context_exa,crawling_exa," +
  "company_research_exa,linkedin_search_exa,deep_researcher_start,deep_researcher_check";

export function resolveMcpConfig(
  env: NodeJS.ProcessEnv,
  apiKey: string | undefined,
): McpConfig {
  const rawUrl = env.EXA_MCP_URL?.trim();
  const baseUrl = rawUrl && rawUrl.length > 0 ? rawUrl : DEFAULT_MCP_URL;
  const tools = env.EXA_MCP_TOOLS?.trim();
  const withTools = tools
    ? setQueryParam(baseUrl, "tools", tools, true)
    : setQueryParam(baseUrl, "tools", DEFAULT_MCP_TOOLS, false);
  const withKey = apiKey
    ? setQueryParam(withTools, "exaApiKey", apiKey, false)
    : withTools;

  return { url: withKey };
}

export async function callMcpTool(
  config: McpConfig,
  name: string,
  args: Record<string, unknown>,
  factory: McpConnectionFactory = createMcpConnection,
): Promise<McpToolResult> {
  const connection = await factory(config);
  try {
    const tools = await connection.listTools();
    if (!tools.some((tool) => tool.name === name)) {
      throw new McpToolUnavailableError(name);
    }
    return await connection.callTool(name, args);
  } finally {
    await connection.close();
  }
}

export function formatMcpToolResult(result: McpToolResult): string {
  if ("structuredContent" in result && result.structuredContent) {
    return JSON.stringify(result.structuredContent, null, 2);
  }

  if ("toolResult" in result) {
    return typeof result.toolResult === "string"
      ? result.toolResult
      : JSON.stringify(result.toolResult, null, 2);
  }

  const textBlocks: string[] = result.content.map(contentBlockToText);
  return textBlocks.filter((item) => item.length > 0).join("\n");
}

export async function createMcpConnection(
  config: McpConfig,
  deps?: {
    clientCtor?: ClientConstructor;
    transportCtor?: TransportConstructor;
  },
): Promise<McpConnection> {
  const clientCtor = deps?.clientCtor ?? (Client as ClientConstructor);
  const transportCtor =
    deps?.transportCtor ??
    (StreamableHTTPClientTransport as unknown as TransportConstructor);
  const client = new clientCtor(
    { name: "exa-search-cli", version: "1.0.0" },
    { capabilities: {} },
  );
  const transport = new transportCtor(new URL(config.url));
  await client.connect(transport as unknown as Transport);

  return {
    listTools: async () => (await client.listTools()).tools,
    callTool: async (name, args) =>
      client.callTool({
        name,
        arguments: args,
      }),
    close: async () => {
      await client.close();
    },
  };
}

function setQueryParam(
  url: string,
  key: string,
  value: string,
  overwrite: boolean,
): string {
  const nextUrl = new URL(url);
  if (overwrite || !nextUrl.searchParams.has(key)) {
    nextUrl.searchParams.set(key, value);
  }
  return nextUrl.toString();
}

function contentBlockToText(block: ContentBlock): string {
  switch (block.type) {
    case "text":
      return block.text;
    case "resource_link":
      return `Resource: ${block.uri}`;
    case "resource":
      if ("text" in block.resource) {
        return block.resource.text;
      }
      return `Resource: ${block.resource.uri}`;
    case "image":
      return "[image]";
    case "audio":
      return "[audio]";
    default:
      return "";
  }
}
