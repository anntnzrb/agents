import type {
  AnswerOptions,
  AnswerResponse,
  ContentsOptions,
  RegularSearchOptions,
  Research,
  ResearchCreateRequest,
  SearchResponse,
  TextContentsOptions,
} from "exa-js";

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

export type SearchType = "auto" | "fast" | "deep";
export type LinkedInSearchType = "profiles" | "companies" | "all";

export type TextResult = { kind: "text"; text: string };
export type SearchOutput =
  | { kind: "search"; data: SearchResponse<ContentsOptions> }
  | TextResult;
export type ResearchOutput = { kind: "research"; data: Research } | TextResult;

export type SearchOptionsInput = {
  numResults?: RegularSearchOptions["numResults"];
  type?: SearchType;
  contents?: {
    text?: true | TextContentsOptions;
  };
};

export type ContentsOptionsInput = {
  text?: true | TextContentsOptions;
};

export type ResearchStartOptions = {
  model?: ResearchCreateRequest["model"];
};

export type Command =
  | { kind: "search"; query: string; options: SearchOptionsInput }
  | { kind: "contents"; urls: string[]; options: ContentsOptionsInput }
  | { kind: "answer"; query: string; options: AnswerOptions }
  | {
      kind: "research-start";
      instructions: string;
      options: ResearchStartOptions;
    }
  | { kind: "research-check"; id: string }
  | { kind: "deep-search"; objective: string; queries?: string[] }
  | { kind: "code-context"; query: string; tokensNum?: number }
  | { kind: "company-research"; companyName: string; numResults?: number }
  | {
      kind: "linkedin-search";
      query: string;
      searchType?: LinkedInSearchType;
      numResults?: number;
    };

export type ExaClient = {
  search: (
    query: string,
    options?: SearchOptionsInput,
  ) => Promise<SearchOutput>;
  getContents: (
    urls: string[] | string,
    options?: ContentsOptionsInput,
  ) => Promise<SearchOutput>;
  answer: (query: string, options?: AnswerOptions) => Promise<AnswerResponse>;
  research: {
    create: (params: {
      instructions: string;
      model?: ResearchCreateRequest["model"];
    }) => Promise<ResearchOutput>;
    get: (
      id: string,
      options?: { stream?: false; events?: boolean },
    ) => Promise<ResearchOutput>;
  };
  deepSearch: (objective: string, queries?: string[]) => Promise<TextResult>;
  codeContext: (query: string, tokensNum?: number) => Promise<TextResult>;
  companyResearch: (
    companyName: string,
    numResults?: number,
  ) => Promise<TextResult>;
  linkedinSearch: (
    query: string,
    searchType?: LinkedInSearchType,
    numResults?: number,
  ) => Promise<TextResult>;
};
