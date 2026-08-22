import { Effect } from "effect";
import {
  CliError,
  ContractError,
  FeedChoice,
  ProvenanceData,
  ProviderError,
  RankingChoice,
} from "#models";
import {
  normalizeConversationPayload,
  normalizePagePayload,
  normalizeQuery,
  normalizeStatusPayload,
  statusIdFromTarget,
  validateCount,
  validateCursor,
  validateFeed,
  validateHandle,
  validateLang,
  validateNumericId,
  validateProvider,
  validateRankingMode,
} from "#contracts";
import { type FetchResult, FxTwitterClient } from "#provider";

export interface FetchCommandInput {
  readonly command: "fetch";
  readonly target: string;
  readonly provider?: string | undefined;
  readonly lang?: string | undefined;
  readonly summary?: boolean | undefined;
  readonly pretty?: boolean | undefined;
}

export interface UserPostsCommandInput {
  readonly command: "user-posts";
  readonly handle: string;
  readonly count?: number | undefined;
  readonly cursor?: string | undefined;
  readonly includeReplies?: boolean | undefined;
  readonly summary?: boolean | undefined;
  readonly pretty?: boolean | undefined;
}

export interface SearchCommandInput {
  readonly command: "search";
  readonly query: string;
  readonly count?: number | undefined;
  readonly feed?: FeedChoice | undefined;
  readonly cursor?: string | undefined;
  readonly summary?: boolean | undefined;
  readonly pretty?: boolean | undefined;
}

export interface ConversationCommandInput {
  readonly command: "conversation";
  readonly id: string;
  readonly rankingMode?: RankingChoice | undefined;
  readonly cursor?: string | undefined;
  readonly summary?: boolean | undefined;
  readonly pretty?: boolean | undefined;
}

export type CommandInput =
  | FetchCommandInput
  | UserPostsCommandInput
  | SearchCommandInput
  | ConversationCommandInput;

function buildProvenance(result: FetchResult): ProvenanceData {
  const status = result.provider_status ?? result.http_status;
  return {
    provider: "fxtwitter",
    official: false,
    auth_mode: "none",
    source_url: result.source_url,
    endpoint: result.endpoint,
    fetched_at: result.fetched_at,
    provider_status: status,
  };
}

function withProvenance(
  data: Record<string, unknown>,
  result: FetchResult
): Record<string, unknown> {
  return { ...data, ...buildProvenance(result) };
}

function enrichContractError(error: ContractError, result: FetchResult): ContractError {
  const details = { ...error.details };
  if (!("source_url" in details)) {
    details["source_url"] = result.source_url;
  }
  if (!("endpoint" in details)) {
    details["endpoint"] = result.endpoint;
  }
  const status = result.provider_status ?? result.http_status;
  if (!("provider_status" in details)) {
    details["provider_status"] = status;
  }
  if (!("http_status" in details)) {
    details["http_status"] = result.http_status;
  }
  return new ContractError({
    code: error.code,
    message: error.message,
    details,
  });
}

export function runCommand(
  input: CommandInput
): Effect.Effect<Record<string, unknown>, CliError | ProviderError | ContractError, FxTwitterClient> {
  return Effect.gen(function* () {
    const client = yield* FxTwitterClient;

    switch (input.command) {
      case "fetch": {
        let id: string;
        let targetUrl: string | undefined;
        const params: [string, string][] = [];
        try {
          const parsedTarget = statusIdFromTarget(input.target);
          id = parsedTarget.id;
          targetUrl = parsedTarget.targetUrl;
          if (input.lang) {
            validateLang(input.lang);
            params.push(["lang", input.lang]);
          }
          if (input.provider) {
            validateProvider(input.provider);
          }
        } catch (err) {
          if (err instanceof CliError || err instanceof ContractError || err instanceof ProviderError) {
            return yield* Effect.fail(err);
          }
          throw err;
        }

        const endpoint = `/2/status/${id}`;
        const result = yield* client.requestJson(endpoint, params);

        let normalized: { post: unknown };
        try {
          normalized = normalizeStatusPayload(result.payload);
        } catch (err) {
          if (err instanceof ContractError) {
            return yield* Effect.fail(enrichContractError(err, result));
          }
          return yield* Effect.fail(
            new ContractError({
              code: "invalid_provider_payload",
              message: "provider status normalization did not return an object",
              details: {
                source_url: result.source_url,
                endpoint: result.endpoint,
                http_status: result.http_status,
                provider_status: result.provider_status ?? result.http_status,
              },
            })
          );
        }

        const data: Record<string, unknown> = {
          post: normalized.post,
          ...(targetUrl ? { requested_url: targetUrl } : { requested_id: id }),
        };
        return withProvenance(data, result);
      }

      case "user-posts": {
        let handle: string;
        const requestedCount = input.count ?? 20;
        const params: [string, string][] = [
          ["count", String(requestedCount)],
          ["groupthreads", "0"],
        ];
        try {
          handle = validateHandle(input.handle);
          validateCount(requestedCount);
          if (input.cursor) {
            validateCursor(input.cursor);
            params.push(["cursor", input.cursor]);
          }
          if (input.includeReplies) {
            params.push(["with_replies", "1"]);
          }
        } catch (err) {
          if (err instanceof CliError || err instanceof ContractError || err instanceof ProviderError) {
            return yield* Effect.fail(err);
          }
          throw err;
        }

        const endpoint = `/2/profile/${handle}/statuses`;
        const result = yield* client.requestJson(endpoint, params);

        let page: Record<string, unknown>;
        try {
          page = normalizePagePayload(result.payload, requestedCount);
        } catch (err) {
          if (err instanceof ContractError) {
            return yield* Effect.fail(enrichContractError(err, result));
          }
          return yield* Effect.fail(
            new ContractError({
              code: "invalid_provider_payload",
              message: "provider page normalization did not return an object",
              details: {
                source_url: result.source_url,
                endpoint: result.endpoint,
                http_status: result.http_status,
                provider_status: result.provider_status ?? result.http_status,
              },
            })
          );
        }

        const data: Record<string, unknown> = {
          handle,
          ...page,
        };
        return withProvenance(data, result);
      }

      case "search": {
        let query: string;
        const requestedCount = input.count ?? 30;
        const feed = input.feed ?? "latest";
        const params: [string, string][] = [];
        try {
          query = normalizeQuery(input.query);
          validateCount(requestedCount);
          validateFeed(feed);
          params.push(["q", query], ["count", String(requestedCount)], ["feed", feed]);
          if (input.cursor) {
            validateCursor(input.cursor);
            params.push(["cursor", input.cursor]);
          }
        } catch (err) {
          if (err instanceof CliError || err instanceof ContractError || err instanceof ProviderError) {
            return yield* Effect.fail(err);
          }
          throw err;
        }

        const endpoint = `/2/search`;
        const result = yield* client.requestJson(endpoint, params);

        let page: Record<string, unknown>;
        try {
          page = normalizePagePayload(result.payload, requestedCount);
        } catch (err) {
          if (err instanceof ContractError) {
            return yield* Effect.fail(enrichContractError(err, result));
          }
          return yield* Effect.fail(
            new ContractError({
              code: "invalid_provider_payload",
              message: "provider search page normalization did not return an object",
              details: {
                source_url: result.source_url,
                endpoint: result.endpoint,
                http_status: result.http_status,
                provider_status: result.provider_status ?? result.http_status,
              },
            })
          );
        }

        const data: Record<string, unknown> = {
          query,
          feed,
          ...page,
        };
        return withProvenance(data, result);
      }

      case "conversation": {
        let postId: string;
        const rankingMode = input.rankingMode ?? "likes";
        const params: [string, string][] = [];
        try {
          postId = validateNumericId(input.id);
          validateRankingMode(rankingMode);
          params.push(["ranking_mode", rankingMode]);
          if (input.cursor) {
            validateCursor(input.cursor);
            params.push(["cursor", input.cursor]);
          }
        } catch (err) {
          if (err instanceof CliError || err instanceof ContractError || err instanceof ProviderError) {
            return yield* Effect.fail(err);
          }
          throw err;
        }

        const endpoint = `/2/conversation/${postId}`;
        const result = yield* client.requestJson(endpoint, params);

        let conv: Record<string, unknown>;
        try {
          conv = normalizeConversationPayload(result.payload);
        } catch (err) {
          if (err instanceof ContractError) {
            return yield* Effect.fail(enrichContractError(err, result));
          }
          return yield* Effect.fail(
            new ContractError({
              code: "invalid_provider_payload",
              message: "provider conversation normalization did not return an object",
              details: {
                source_url: result.source_url,
                endpoint: result.endpoint,
                http_status: result.http_status,
                provider_status: result.provider_status ?? result.http_status,
              },
            })
          );
        }

        const data: Record<string, unknown> = {
          requested_id: postId,
          ranking_mode: rankingMode,
          ...conv,
        };
        return withProvenance(data, result);
      }
    }
  });
}
