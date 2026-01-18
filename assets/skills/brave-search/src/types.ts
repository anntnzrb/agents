export type SearchResult = {
  title: string;
  link: string;
  snippet: string;
  content?: string;
};

export type SearchArgs = {
  query: string;
  numResults: number;
  fetchContent: boolean;
};

export type ContentArgs = {
  url: string;
};

export type ExtractedContent = {
  title?: string;
  content: string;
};

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;
