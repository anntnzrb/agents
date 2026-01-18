import Exa from "exa-js";
import type {
  AnswerOptions,
  AnswerResponse,
  ContentsOptions,
  RegularSearchOptions,
  Research,
  ResearchCreateRequest,
  SearchResponse,
  SearchResult,
  TextContentsOptions,
} from "exa-js";
import type {
  ContentsOptionsInput,
  ExaClient,
  LinkedInSearchType,
  ResearchOutput,
  SearchOptionsInput,
  SearchOutput,
  TextResult,
} from "@/types";
import {
  callMcpTool,
  formatMcpToolResult,
  resolveMcpConfig,
  type McpConfig,
} from "@/mcp";

type ExaLike = {
  search: (
    query: string,
    options?: RegularSearchOptions,
  ) => Promise<SearchResponse<ContentsOptions>>;
  getContents: (
    urls: string | string[] | SearchResult<ContentsOptions>[],
    options?: ContentsOptions,
  ) => Promise<SearchResponse<ContentsOptions>>;
  answer: (query: string, options?: AnswerOptions) => Promise<AnswerResponse>;
  research: {
    create: (params: {
      instructions: string;
      model?: ResearchCreateRequest["model"];
      outputSchema?: Record<string, unknown>;
    }) => Promise<Research>;
    get: (
      id: string,
      options?: { stream?: false; events?: boolean },
    ) => Promise<Research>;
  };
};

type ExaConstructor = new (apiKey: string, baseURL?: string) => ExaLike;

export type McpCaller = typeof callMcpTool;

export function createExaClient(
  apiKey: string,
  ExaCtor: ExaConstructor = Exa,
  options?: {
    mcpConfig?: McpConfig;
    mcpCaller?: McpCaller;
  },
): ExaClient {
  const exa = new ExaCtor(apiKey);
  const mcpConfig = options?.mcpConfig ?? resolveMcpConfig(process.env, apiKey);
  const mcpCaller = options?.mcpCaller ?? callMcpTool;

  return {
    search: async (query: string, options?: SearchOptionsInput) => {
      const mcpArgs = toMcpSearchArgs(query, options);
      const result = await callTextTool(
        mcpConfig,
        "web_search_exa",
        mcpArgs,
        mcpCaller,
      );
      return result;
    },
    getContents: async (urls, options) => {
      const mcpArgs = toMcpCrawlArgs(urls, options);
      const result = await callTextTool(
        mcpConfig,
        "crawling_exa",
        mcpArgs,
        mcpCaller,
      );
      return result;
    },
    answer: (query, options) => exa.answer(query, options),
    research: {
      create: async (params) => {
        const mcpArgs = toMcpResearchStartArgs(params);
        const result = await callTextTool(
          mcpConfig,
          "deep_researcher_start",
          mcpArgs,
          mcpCaller,
        );
        return result;
      },
      get: async (id, options) => {
        if (options?.events) {
          throw new Error("Unsupported research-check option: events.");
        }
        const result = await callTextTool(
          mcpConfig,
          "deep_researcher_check",
          { taskId: id },
          mcpCaller,
        );
        return result;
      },
    },
    deepSearch: async (objective, queries) => {
      return callTextTool(
        mcpConfig,
        "deep_search_exa",
        {
          objective,
          ...(queries && queries.length > 0 ? { search_queries: queries } : {}),
        },
        mcpCaller,
      );
    },
    codeContext: async (query, tokensNum) => {
      return callTextTool(
        mcpConfig,
        "get_code_context_exa",
        {
          query,
          ...(tokensNum ? { tokensNum } : {}),
        },
        mcpCaller,
      );
    },
    companyResearch: async (companyName, numResults) => {
      return callTextTool(
        mcpConfig,
        "company_research_exa",
        {
          companyName,
          ...(numResults ? { numResults } : {}),
        },
        mcpCaller,
      );
    },
    linkedinSearch: async (query, searchType, numResults) => {
      return callTextTool(
        mcpConfig,
        "linkedin_search_exa",
        {
          query,
          ...(searchType ? { searchType } : {}),
          ...(numResults ? { numResults } : {}),
        },
        mcpCaller,
      );
    },
  };
}

async function callTextTool(
  config: { url: string },
  name: string,
  args: Record<string, unknown>,
  mcpCaller: McpCaller,
): Promise<TextResult> {
  const result = await mcpCaller(config, name, args);
  const text = formatMcpToolResult(result);
  if ("isError" in result && result.isError) {
    throw new Error(text || `MCP tool error: ${name}`);
  }
  return { kind: "text", text };
}

function toMcpSearchArgs(
  query: string,
  options?: SearchOptionsInput,
): Record<string, unknown> {
  const contextMaxCharacters = extractMaxCharacters(options?.contents?.text);
  return {
    query,
    ...(options?.numResults ? { numResults: options.numResults } : {}),
    ...(options?.type ? { type: options.type } : {}),
    ...(contextMaxCharacters ? { contextMaxCharacters } : {}),
  };
}

function toMcpCrawlArgs(
  urls: string[] | string,
  options?: ContentsOptionsInput,
): Record<string, unknown> {
  const url = Array.isArray(urls) ? urls[0] : urls;
  if (Array.isArray(urls) && urls.length !== 1) {
    throw new Error("Unsupported contents option: multiple URLs.");
  }

  const maxCharacters = extractMaxCharacters(options?.text);

  return {
    url,
    ...(maxCharacters ? { maxCharacters } : {}),
  };
}

function toMcpResearchStartArgs(params: {
  instructions: string;
  model?: ResearchCreateRequest["model"];
}): Record<string, unknown> {
  if (params.model && !isMcpResearchModel(params.model)) {
    throw new Error(`Unsupported research model: ${params.model}.`);
  }
  return {
    instructions: params.instructions,
    ...(params.model ? { model: params.model } : {}),
  };
}

function isMcpResearchModel(
  model: ResearchCreateRequest["model"],
): model is "exa-research" | "exa-research-pro" {
  return model === "exa-research" || model === "exa-research-pro";
}

type TextOption = TextContentsOptions | true | undefined;

function extractMaxCharacters(text: TextOption): number | undefined {
  if (isTextOptions(text)) {
    return text.maxCharacters;
  }
  return undefined;
}

function isTextOptions(value: TextOption): value is TextContentsOptions {
  return !!value && typeof value === "object";
}
