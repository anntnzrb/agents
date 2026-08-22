import { Config, Context, DateTime, Duration, Effect, Layer } from "effect";
import { HttpClient, HttpClientRequest } from "effect/unstable/http";
import {
  CliError,
  DEFAULT_BASE_URL,
  DEFAULT_TIMEOUT,
  ProviderError,
} from "#models";

const MAX_REASON_LENGTH = 160;
const CONTROL_CHAR_MIN = 32;
const CONTROL_CHAR_MAX = 127;

export function compactText(value: unknown): string {
  const text = String(value ?? "").replace(/\r/g, " ").replace(/\n/g, " ").trim();
  if (text.length > MAX_REASON_LENGTH) {
    return text.slice(0, MAX_REASON_LENGTH - 1) + "…";
  }
  return text;
}

export function validateBaseUrl(baseUrl: string): string {
  if (typeof baseUrl !== "string" || !baseUrl || baseUrl.trim() !== baseUrl) {
    throw new CliError({
      code: "invalid_base_url",
      message: "base URL must be a non-empty HTTPS URL",
      details: {},
    });
  }
  for (let i = 0; i < baseUrl.length; i++) {
    const code = baseUrl.charCodeAt(i);
    if (code < CONTROL_CHAR_MIN || code > CONTROL_CHAR_MAX) {
      throw new CliError({
        code: "invalid_base_url",
        message: "base URL must not contain surrounding whitespace",
        details: {},
      });
    }
  }
  let parsed: URL;
  try {
    parsed = new URL(baseUrl);
  } catch (err) {
    throw new CliError({
      code: "invalid_base_url",
      message: "base URL is malformed",
      details: { reason: compactText(err) },
    });
  }
  if (parsed.protocol !== "https:") {
    throw new CliError({
      code: "invalid_base_url",
      message: "base URL must use HTTPS and include a host",
      details: {},
    });
  }
  if (!parsed.hostname) {
    throw new CliError({
      code: "invalid_base_url",
      message: "base URL must use HTTPS and include a host",
      details: {},
    });
  }
  if (parsed.username || parsed.password) {
    throw new CliError({
      code: "invalid_base_url",
      message: "base URL must not include credentials",
      details: {},
    });
  }
  if (parsed.search || parsed.hash) {
    throw new CliError({
      code: "invalid_base_url",
      message: "base URL must not include a query or fragment",
      details: {},
    });
  }
  return baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
}

export function validateTimeout(timeout: number): number {
  if (typeof timeout !== "number" || !Number.isFinite(timeout) || timeout <= 0 || timeout > 60) {
    throw new ProviderError({
      code: "invalid_timeout",
      message: "timeout must be greater than 0 and at most 60 seconds",
      details: {},
    });
  }
  return timeout;
}

export function validateEndpoint(endpoint: string): string {
  if (typeof endpoint !== "string" || !endpoint || !endpoint.startsWith("/")) {
    throw new ProviderError({
      code: "invalid_endpoint",
      message: "endpoint must be a non-empty absolute path",
      details: {},
    });
  }
  if (endpoint.startsWith("//")) {
    throw new ProviderError({
      code: "invalid_endpoint",
      message: "endpoint must not be a network-path reference",
      details: {},
    });
  }
  for (let i = 0; i < endpoint.length; i++) {
    const code = endpoint.charCodeAt(i);
    if (code < CONTROL_CHAR_MIN || code > CONTROL_CHAR_MAX) {
      throw new ProviderError({
        code: "invalid_endpoint",
        message: "endpoint contains a control character",
        details: {},
      });
    }
  }
  let parsed: URL;
  try {
    parsed = new URL(endpoint, "https://dummy.local");
  } catch {
    throw new ProviderError({
      code: "invalid_endpoint",
      message: "endpoint is malformed",
      details: {},
    });
  }
  if (parsed.search || parsed.hash) {
    throw new ProviderError({
      code: "invalid_endpoint",
      message: "endpoint must contain only a path",
      details: {},
    });
  }
  return endpoint;
}

export function validateParams(
  params?: readonly (readonly [string, string])[]
): readonly (readonly [string, string])[] {
  if (!params) return [];
  if (!Array.isArray(params)) {
    throw new ProviderError({
      code: "invalid_endpoint",
      message: "query parameters must be a sequence of pairs",
      details: {},
    });
  }
  for (const pair of params) {
    if (!Array.isArray(pair) || pair.length !== 2) {
      throw new ProviderError({
        code: "invalid_endpoint",
        message: "query parameters must be a sequence of pairs",
        details: {},
      });
    }
    const [key, value] = pair;
    if (typeof key !== "string" || typeof value !== "string") {
      throw new ProviderError({
        code: "invalid_endpoint",
        message: "query parameter names and values must be strings",
        details: {},
      });
    }
  }
  return params;
}

export function encodeQuery(params: readonly (readonly [string, string])[]): string {
  return params
    .map(([k, v]) => {
      const ek = encodeURIComponent(k).replace(/%20/g, "+");
      const ev = encodeURIComponent(v).replace(/%20/g, "+");
      return `${ek}=${ev}`;
    })
    .join("&");
}

export function buildUrl(
  baseUrl: string,
  endpoint: string,
  params?: readonly (readonly [string, string])[]
): string {
  const validatedBase = validateBaseUrl(baseUrl);
  const validatedEndpoint = validateEndpoint(endpoint);
  const validatedPairs = validateParams(params);
  const query = encodeQuery(validatedPairs);
  return `${validatedBase}${validatedEndpoint}` + (query ? `?${query}` : "");
}

export interface FetchResult {
  readonly payload: unknown;
  readonly bytes: number;
  readonly http_status: number;
  readonly provider_status: number | null;
  readonly source_url: string;
  readonly endpoint: string;
  readonly fetched_at: string;
}

export class FxTwitterClient extends Context.Service<
  FxTwitterClient,
  {
    readonly requestJson: (
      endpoint: string,
      params?: readonly (readonly [string, string])[]
    ) => Effect.Effect<FetchResult, ProviderError | CliError>;
  }
>()("FxTwitterClient") {}

function decodePayload(
  text: string,
  sourceUrl: string,
  endpoint: string,
  httpStatus: number
): { payload: unknown; byteCount: number } {
  const byteCount = Buffer.byteLength(text, "utf8");
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new ProviderError({
      code: "invalid_json",
      message: "provider response was not valid JSON",
      details: {
        source_url: sourceUrl,
        endpoint,
        http_status: httpStatus,
        byte_count: byteCount,
      },
    });
  }
  return { payload, byteCount };
}

function checkProviderStatus(
  payload: unknown,
  httpStatus: number,
  sourceUrl: string,
  endpoint: string,
  byteCount: number
): number | null {
  if (typeof payload !== "object" || payload === null) {
    throw new ProviderError({
      code: "invalid_payload",
      message: "provider response must be a JSON object",
      details: {
        source_url: sourceUrl,
        endpoint,
        http_status: httpStatus,
        byte_count: byteCount,
      },
    });
  }

  const obj = payload as Record<string, unknown>;
  if (!("code" in obj) || obj["code"] === undefined) {
    return null;
  }

  const rawCode = obj["code"];
  if (typeof rawCode !== "number" || !Number.isFinite(rawCode) || !Number.isInteger(rawCode)) {
    throw new ProviderError({
      code: "invalid_provider_status",
      message: "provider status code is malformed",
      details: {
        source_url: sourceUrl,
        endpoint,
        http_status: httpStatus,
        byte_count: byteCount,
      },
    });
  }

  if (rawCode >= 400) {
    throw new ProviderError({
      code: "provider_error",
      message: `provider returned API status ${rawCode}`,
      details: {
        source_url: sourceUrl,
        endpoint,
        http_status: httpStatus,
        provider_status: rawCode,
        byte_count: byteCount,
      },
    });
  }

  return rawCode;
}

export function makeFxTwitterClient(
  httpClient: HttpClient.HttpClient,
  baseUrl: string,
  timeoutSeconds: number = DEFAULT_TIMEOUT
): {
  readonly requestJson: (
    endpoint: string,
    params?: readonly (readonly [string, string])[]
  ) => Effect.Effect<FetchResult, ProviderError | CliError>;
} {
  const effectiveBaseUrl = validateBaseUrl(baseUrl);
  const effectiveTimeout = validateTimeout(timeoutSeconds);

  return {
    requestJson: (endpoint: string, params?: readonly (readonly [string, string])[]) =>
      Effect.gen(function* () {
        let sourceUrl: string;
        try {
          sourceUrl = buildUrl(effectiveBaseUrl, endpoint, params);
        } catch (err) {
          if (err instanceof CliError || err instanceof ProviderError) {
            return yield* Effect.fail(err);
          }
          return yield* Effect.fail(
            new ProviderError({
              code: "invalid_endpoint",
              message: "failed to construct request URL",
              details: { reason: compactText(err) },
            })
          );
        }

        const request = HttpClientRequest.get(sourceUrl).pipe(
          HttpClientRequest.setHeaders({
            accept: "application/json",
            "user-agent": "x-research/1",
          })
        );

        const response = yield* httpClient.execute(request).pipe(
          Effect.timeout(Duration.seconds(effectiveTimeout)),
          Effect.mapError((err) => {
            if (err instanceof ProviderError || err instanceof CliError) {
              return err;
            }
            return new ProviderError({
              code: "network_error",
              message: "provider request failed",
              details: {
                source_url: sourceUrl,
                endpoint,
                reason: compactText(err),
              },
            });
          })
        );

        const httpStatus = response.status;
        if (httpStatus < 200 || httpStatus >= 300) {
          return yield* Effect.fail(
            new ProviderError({
              code: "http_error",
              message: `provider returned HTTP ${httpStatus}`,
              details: {
                source_url: sourceUrl,
                endpoint,
                http_status: httpStatus,
              },
            })
          );
        }

        const text = yield* response.text.pipe(
          Effect.mapError((err) =>
            new ProviderError({
              code: "network_error",
              message: "provider request failed",
              details: {
                source_url: sourceUrl,
                endpoint,
                reason: compactText(err),
              },
            })
          )
        );

        let decoded: { payload: unknown; byteCount: number };
        try {
          decoded = decodePayload(text, sourceUrl, endpoint, httpStatus);
        } catch (err) {
          if (err instanceof ProviderError || err instanceof CliError) {
            return yield* Effect.fail(err);
          }
          return yield* Effect.fail(
            new ProviderError({
              code: "invalid_json",
              message: "provider response was not valid JSON",
              details: {
                source_url: sourceUrl,
                endpoint,
                http_status: httpStatus,
              },
            })
          );
        }

        let providerStatus: number | null;
        try {
          providerStatus = checkProviderStatus(
            decoded.payload,
            httpStatus,
            sourceUrl,
            endpoint,
            decoded.byteCount
          );
        } catch (err) {
          if (err instanceof ProviderError || err instanceof CliError) {
            return yield* Effect.fail(err);
          }
          return yield* Effect.fail(
            new ProviderError({
              code: "invalid_payload",
              message: "provider response validation failed",
              details: {
                source_url: sourceUrl,
                endpoint,
                http_status: httpStatus,
              },
            })
          );
        }

        const now = yield* DateTime.now;
        const utc = DateTime.toUtc(now);
        const fetchedAt = DateTime.formatIso(utc).replace(/\.\d{3}/, "");

        return {
          payload: decoded.payload,
          bytes: decoded.byteCount,
          http_status: httpStatus,
          provider_status: providerStatus,
          source_url: sourceUrl,
          endpoint,
          fetched_at: fetchedAt,
        };
      }),
  };
}

export const FxTwitterClientLive = Layer.effect(
  FxTwitterClient,
  Effect.gen(function* () {
    const httpClient = yield* HttpClient.HttpClient;
    const configuredBaseUrl = yield* Config.string("X_RESEARCH_BASE_URL").pipe(
      Config.withDefault(DEFAULT_BASE_URL)
    );
    return makeFxTwitterClient(httpClient, configuredBaseUrl, DEFAULT_TIMEOUT);
  })
);
