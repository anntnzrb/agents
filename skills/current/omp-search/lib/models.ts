import { Schema } from "effect";

export interface SearchSource {
  readonly title: string;
  readonly domain: string;
  readonly age: string | null;
}

export const SearchSource = Schema.Struct({
  title: Schema.String,
  domain: Schema.String,
  age: Schema.NullOr(Schema.String),
});

export interface SearchError {
  readonly code: string;
  readonly message: string;
}

export const SearchError = Schema.Struct({
  code: Schema.String,
  message: Schema.String,
});

export interface SearchSuccessPayload {
  readonly ok: true;
  readonly query: string;
  readonly provider: string;
  readonly providers: readonly string[];
  readonly providers_count: number;
  readonly answer: string;
  readonly sources: readonly SearchSource[];
  readonly sources_count: number;
  readonly truncated: boolean;
  readonly compact: boolean;
  readonly parsed: boolean;
  readonly exit_code: 0;
  readonly raw?: string | undefined;
}

export const SearchSuccessPayload = Schema.Struct({
  ok: Schema.Literal(true),
  query: Schema.String,
  provider: Schema.String,
  providers: Schema.Array(Schema.String),
  providers_count: Schema.Number,
  answer: Schema.String,
  sources: Schema.Array(SearchSource),
  sources_count: Schema.Number,
  truncated: Schema.Boolean,
  compact: Schema.Boolean,
  parsed: Schema.Boolean,
  exit_code: Schema.Literal(0),
  raw: Schema.optional(Schema.String),
});

export interface SearchFailurePayload {
  readonly ok: false;
  readonly query: string;
  readonly provider: string;
  readonly providers?: readonly string[] | undefined;
  readonly providers_count?: number | undefined;
  readonly answer: "";
  readonly sources: readonly SearchSource[];
  readonly sources_count?: number | undefined;
  readonly truncated: false;
  readonly compact: boolean;
  readonly parsed: boolean;
  readonly exit_code: number;
  readonly error: SearchError;
  readonly raw?: string | undefined;
  readonly diagnostics?: string | undefined;
}

export const SearchFailurePayload = Schema.Struct({
  ok: Schema.Literal(false),
  query: Schema.String,
  provider: Schema.String,
  providers: Schema.optional(Schema.Array(Schema.String)),
  providers_count: Schema.optional(Schema.Number),
  answer: Schema.Literal(""),
  sources: Schema.Array(SearchSource),
  sources_count: Schema.optional(Schema.Number),
  truncated: Schema.Literal(false),
  compact: Schema.Boolean,
  parsed: Schema.Boolean,
  exit_code: Schema.Number,
  error: SearchError,
  raw: Schema.optional(Schema.String),
  diagnostics: Schema.optional(Schema.String),
});

export type SearchResult = SearchSuccessPayload | SearchFailurePayload;

export const SearchResult = Schema.Union([SearchSuccessPayload, SearchFailurePayload]);

export interface CliOptions {
  readonly queryWords: readonly string[];
  readonly provider?: string | undefined;
  readonly providers?: readonly string[] | undefined;
  readonly single?: boolean | undefined;
  readonly recency?: "day" | "week" | "month" | "year" | undefined;
  readonly limit?: number | undefined;
  readonly full?: boolean | undefined;
  readonly includeRaw?: boolean | undefined;
  readonly timeout?: number | undefined;
  readonly ompBin?: string | undefined;
}

export class OmpBinaryNotFoundError extends Schema.TaggedError<OmpBinaryNotFoundError>()(
  "OmpBinaryNotFoundError",
  {
    message: Schema.String,
  }
) {}

export class OmpExecutionError extends Schema.TaggedError<OmpExecutionError>()(
  "OmpExecutionError",
  {
    exitCode: Schema.Number,
    stdout: Schema.String,
    stderr: Schema.String,
    message: Schema.String,
  }
) {}

export class OmpTimeoutError extends Schema.TaggedError<OmpTimeoutError>()(
  "OmpTimeoutError",
  {
    timeoutSeconds: Schema.Number,
    message: Schema.String,
    partialStdout: Schema.String,
  }
) {}
