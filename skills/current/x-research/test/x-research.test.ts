import { describe, expect, test } from "bun:test";
import { Effect, Layer } from "effect";
import { HttpClient, HttpClientResponse } from "effect/unstable/http";
import {
  CliError,
  ContractError,
  DEFAULT_BASE_URL,
  ProviderError,
  SCHEMA_VERSION,
} from "#models";
import {
  actualType,
  normalizeConversationPayload,
  normalizePagePayload,
  normalizePost,
  normalizeProfile,
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
import {
  buildUrl,
  encodeQuery,
  FxTwitterClient,
  makeFxTwitterClient,
  validateBaseUrl,
  validateEndpoint,
} from "#provider";
import { runCommand } from "#commands";
import { summaryData, summaryPost } from "#summary";

describe("Validation and Contracts", () => {
  test("validateHandle accepts valid handles and rejects invalid", () => {
    expect(validateHandle("OpenAI")).toBe("OpenAI");
    expect(validateHandle("user_123")).toBe("user_123");
    expect(() => validateHandle("")).toThrow(CliError);
    expect(() => validateHandle("@OpenAI")).toThrow(CliError);
    expect(() => validateHandle("invalid handle")).toThrow(CliError);
  });

  test("validateNumericId accepts numeric strings only", () => {
    expect(validateNumericId("123456789")).toBe("123456789");
    expect(() => validateNumericId("abc")).toThrow(CliError);
    expect(() => validateNumericId("123a")).toThrow(CliError);
    expect(() => validateNumericId("")).toThrow(CliError);
  });

  test("statusIdFromTarget extracts ID from numeric and status URLs", () => {
    expect(statusIdFromTarget("1890000000000000000")).toEqual({ id: "1890000000000000000" });
    expect(statusIdFromTarget("https://x.com/OpenAI/status/1890000000000000000")).toEqual({
      id: "1890000000000000000",
      targetUrl: "https://x.com/OpenAI/status/1890000000000000000",
    });
    expect(statusIdFromTarget("https://twitter.com/user/status/12345/")).toEqual({
      id: "12345",
      targetUrl: "https://twitter.com/user/status/12345/",
    });

    expect(() => statusIdFromTarget("http://x.com/user/status/123")).toThrow(CliError);
    expect(() => statusIdFromTarget("https://evil.com/user/status/123")).toThrow(CliError);
    expect(() => statusIdFromTarget("https://x.com/user/other/123")).toThrow(CliError);
    expect(() => statusIdFromTarget("https://x.com/user/status/123?query=1")).toThrow(CliError);
    expect(() => statusIdFromTarget("")).toThrow(CliError);
  });

  test("normalizeQuery collapses whitespace and rejects empty", () => {
    expect(normalizeQuery("  hello   world  ")).toBe("hello world");
    expect(normalizeQuery("from:OpenAI   release")).toBe("from:OpenAI release");
    expect(() => normalizeQuery("   ")).toThrow(CliError);
    expect(() => normalizeQuery(123)).toThrow(CliError);
  });

  test("validateCount restricts to integers 1..100", () => {
    expect(validateCount(1)).toBe(1);
    expect(validateCount(20)).toBe(20);
    expect(validateCount(100)).toBe(100);
    expect(() => validateCount(0)).toThrow(ContractError);
    expect(() => validateCount(101)).toThrow(ContractError);
    expect(() => validateCount(20.5)).toThrow(ContractError);
    expect(() => validateCount("20")).toThrow(ContractError);
  });

  test("validateCursor, Lang, Feed, RankingMode, Provider", () => {
    expect(validateCursor("bottom_cursor_token")).toBe("bottom_cursor_token");
    expect(() => validateCursor("  ")).toThrow(CliError);

    expect(validateLang("en")).toBe("en");
    expect(() => validateLang(" ")).toThrow(CliError);

    expect(validateFeed("latest")).toBe("latest");
    expect(validateFeed("top")).toBe("top");
    expect(validateFeed("media")).toBe("media");
    expect(() => validateFeed("invalid")).toThrow(CliError);

    expect(validateRankingMode("likes")).toBe("likes");
    expect(validateRankingMode("recency")).toBe("recency");
    expect(() => validateRankingMode("invalid")).toThrow(CliError);

    expect(validateProvider("fxtwitter")).toBe("fxtwitter");
    expect(() => validateProvider("other")).toThrow(CliError);
  });

  test("actualType returns descriptive types", () => {
    expect(actualType(null)).toBe("null");
    expect(actualType(undefined)).toBe("undefined");
    expect(actualType(true)).toBe("boolean");
    expect(actualType("str")).toBe("string");
    expect(actualType(42)).toBe("number");
    expect(actualType([])).toBe("array");
    expect(actualType({})).toBe("object");
  });
});

describe("URL and Base URL Validation", () => {
  test("validateBaseUrl requires HTTPS, host, no credentials/query/hash", () => {
    expect(validateBaseUrl("https://api.fxtwitter.com")).toBe("https://api.fxtwitter.com");
    expect(validateBaseUrl("https://api.fxtwitter.com/")).toBe("https://api.fxtwitter.com");
    expect(validateBaseUrl("https://proxy.internal:8443/custom")).toBe("https://proxy.internal:8443/custom");

    expect(() => validateBaseUrl("http://api.fxtwitter.com")).toThrow(CliError);
    expect(() => validateBaseUrl("https://user:pass@api.fxtwitter.com")).toThrow(CliError);
    expect(() => validateBaseUrl("https://api.fxtwitter.com?query=1")).toThrow(CliError);
    expect(() => validateBaseUrl("https://api.fxtwitter.com#frag")).toThrow(CliError);
    expect(() => validateBaseUrl("   https://api.fxtwitter.com")).toThrow(CliError);
    expect(() => validateBaseUrl("")).toThrow(CliError);
  });

  test("validateEndpoint enforces absolute path and no query/hash/network-ref", () => {
    expect(validateEndpoint("/2/status/123")).toBe("/2/status/123");
    expect(() => validateEndpoint("//2/status")).toThrow(ProviderError);
    expect(() => validateEndpoint("2/status")).toThrow(ProviderError);
    expect(() => validateEndpoint("/2/status?q=1")).toThrow(ProviderError);
    expect(() => validateEndpoint("/2/status#frag")).toThrow(ProviderError);
  });

  test("encodeQuery uses + for space encoding and preserves insertion order", () => {
    const params: [string, string][] = [
      ["q", "hello world & more"],
      ["count", "20"],
      ["feed", "latest"],
    ];
    const encoded = encodeQuery(params);
    expect(encoded).toBe("q=hello+world+%26+more&count=20&feed=latest");
  });

  test("buildUrl constructs complete URL", () => {
    const url = buildUrl("https://api.fxtwitter.com", "/2/search", [["q", "AI agent"], ["count", "10"]]);
    expect(url).toBe("https://api.fxtwitter.com/2/search?q=AI+agent&count=10");
  });
});

describe("Payload Normalization", () => {
  const samplePost = {
    id: "1001",
    url: "https://x.com/user/status/1001",
    text: "Sample post text",
    created_at: "2026-08-20T12:00:00Z",
    author: {
      id: "auth_1",
      screen_name: "user",
      name: "User Name",
      url: "https://x.com/user",
      verified: true,
    },
    metrics: {
      likes: 10,
      reposts: 5,
      replies: 2,
    },
    lang: "en",
    quote: { id: "999" },
    replying_to: { status: "998" },
  };

  test("normalizeProfile extracts identity and verification fields", () => {
    const prof = normalizeProfile(samplePost.author);
    expect(prof).toEqual({
      id: "auth_1",
      handle: "user",
      name: "User Name",
      url: "https://x.com/user",
      verified: true,
    });
  });

  test("normalizePost normalizes full post and maps metrics/quote/reply", () => {
    const post = normalizePost(samplePost);
    expect(post.id).toBe("1001");
    expect(post.url).toBe("https://x.com/user/status/1001");
    expect(post.text).toBe("Sample post text");
    expect(post.created_at).toBe("2026-08-20T12:00:00Z");
    expect(post.author.handle).toBe("user");
    expect(post.metrics).toEqual({ likes: 10, reposts: 5, replies: 2 });
    expect(post.lang).toBe("en");
    expect(post.quote_id).toBe("999");
    expect(post.reply_to_id).toBe("998");
  });

  test("missing optional post values are omitted", () => {
    const minimalPost = {
      id: "1002",
      url: "https://x.com/user/status/1002",
      text: "",
      created_at: "2026-08-20T12:00:00Z",
      author: {
        id: "auth_2",
      },
    };
    const post = normalizePost(minimalPost);
    expect(post.id).toBe("1002");
    expect(post.metrics).toBeUndefined();
    expect(post.lang).toBeUndefined();
    expect(post.media).toBeUndefined();
    expect(post.quote_id).toBeUndefined();
    expect(post.reply_to_id).toBeUndefined();
    expect(post.author.handle).toBeUndefined();
  });

  test("normalizeStatusPayload handles exact post root", () => {
    const payload = { code: 200, status: samplePost };
    const res = normalizeStatusPayload(payload);
    expect(res.post.id).toBe("1001");
  });

  test("normalizePagePayload validates count, pagination, and cursor states", () => {
    const pageWithCursor = {
      code: 200,
      results: [samplePost],
      cursor: { bottom: "cursor_token_123" },
      profile: samplePost.author,
    };
    const res1 = normalizePagePayload(pageWithCursor, 20);
    expect(res1.requested_count).toBe(20);
    expect(res1.returned_count).toBe(1);
    expect(res1.cursor).toBe("cursor_token_123");
    expect(res1.has_more).toBe(true);
    expect(res1.complete).toBe(false);
    expect(res1.complete_reason).toBe("bounded_page");
    expect(res1.profile?.handle).toBe("user");

    const pageExhausted = {
      code: 200,
      results: [samplePost],
      cursor: null,
    };
    const res2 = normalizePagePayload(pageExhausted, 20);
    expect(res2.cursor).toBeUndefined();
    expect(res2.has_more).toBeUndefined();
    expect(res2.complete).toBe(true);
    expect(res2.complete_reason).toBe("provider_exhausted");

    const pageIncomplete = {
      code: 200,
      results: [samplePost],
    };
    const res3 = normalizePagePayload(pageIncomplete, 20);
    expect(res3.complete).toBe(false);
    expect(res3.complete_reason).toBe("provider_incomplete");
  });

  test("page output is capped to requested_count", () => {
    const posts = [
      { ...samplePost, id: "1" },
      { ...samplePost, id: "2" },
      { ...samplePost, id: "3" },
    ];
    const payload = { code: 200, results: posts };
    const res = normalizePagePayload(payload, 2);
    expect(res.requested_count).toBe(2);
    expect(res.returned_count).toBe(2);
    expect(res.posts.length).toBe(2);
    expect(res.posts[0]!.id).toBe("1");
    expect(res.posts[1]!.id).toBe("2");
  });

  test("normalizeConversationPayload projects target, thread, replies, count", () => {
    const payload = {
      status: samplePost,
      thread: [{ ...samplePost, id: "1002" }],
      replies: [{ ...samplePost, id: "1003" }, { ...samplePost, id: "1004" }],
      cursor: { bottom: "conv_cursor" },
    };
    const res = normalizeConversationPayload(payload);
    expect(res.target.id).toBe("1001");
    expect(res.thread.length).toBe(1);
    expect(res.replies.length).toBe(2);
    expect(res.returned_count).toBe(4);
    expect(res.cursor).toBe("conv_cursor");
    expect(res.has_more).toBe(true);
    expect(res.complete).toBe(false);
    expect(res.complete_reason).toBe("bounded_page");
  });
});

describe("Summary Projections", () => {
  const fullPost = {
    id: "2001",
    url: "https://x.com/user/status/2001",
    text: "Full text content",
    created_at: "2026-08-20T12:00:00Z",
    author: {
      id: "auth_1",
      handle: "user",
      name: "User Name",
      url: "https://x.com/user",
      verified: true,
      extra_junk: "remove",
    },
    metrics: { likes: 100 },
    media: { photos: [{ type: "photo", url: "https://photo.url" }] },
    lang: "en",
    quote_id: "2000",
    reply_to_id: "1999",
  };

  test("summaryPost retains citation identity and full text while omitting metrics/media", () => {
    const projected = summaryPost(fullPost);
    expect(projected["id"]).toBe("2001");
    expect(projected["url"]).toBe("https://x.com/user/status/2001");
    expect(projected["text"]).toBe("Full text content");
    expect(projected["created_at"]).toBe("2026-08-20T12:00:00Z");
    expect(projected["lang"]).toBe("en");
    expect(projected["quote_id"]).toBe("2000");
    expect(projected["reply_to_id"]).toBe("1999");
    expect(projected["author"]).toEqual({
      id: "auth_1",
      handle: "user",
      name: "User Name",
      url: "https://x.com/user",
      verified: true,
    });
    expect(projected["metrics"]).toBeUndefined();
    expect(projected["media"]).toBeUndefined();
  });

  test("summaryData projects fetch, user-posts, search, and conversation payloads", () => {
    const fetchData = {
      requested_id: "2001",
      post: fullPost,
      provider: "fxtwitter",
      official: false,
      auth_mode: "none",
      source_url: "https://api.fxtwitter.com/2/status/2001",
      endpoint: "/2/status/2001",
      fetched_at: "2026-08-22T22:00:00Z",
      provider_status: 200,
    };
    const projectedFetch = summaryData("fetch", fetchData);
    expect(projectedFetch["requested_id"]).toBe("2001");
    expect(projectedFetch["provider"]).toBe("fxtwitter");
    expect(projectedFetch["post"]).toBeDefined();
    expect((projectedFetch["post"] as Record<string, unknown>)["metrics"]).toBeUndefined();

    const pageData = {
      handle: "user",
      profile: fullPost.author,
      posts: [fullPost],
      requested_count: 20,
      returned_count: 1,
      cursor: "cur_123",
      has_more: true,
      complete: false,
      complete_reason: "bounded_page",
      provider: "fxtwitter",
      official: false,
      auth_mode: "none",
      source_url: "https://api.fxtwitter.com/2/profile/user/statuses?count=20&groupthreads=0",
      endpoint: "/2/profile/user/statuses",
      fetched_at: "2026-08-22T22:00:00Z",
      provider_status: 200,
    };
    const projectedPage = summaryData("user-posts", pageData);
    expect(projectedPage["handle"]).toBe("user");
    expect(projectedPage["profile"]).toEqual({
      id: "auth_1",
      handle: "user",
      name: "User Name",
      url: "https://x.com/user",
      verified: true,
    });
    expect((projectedPage["posts"] as Record<string, unknown>[])[0]!["metrics"]).toBeUndefined();
  });
});

describe("In-Memory Client & Command Execution", () => {
  const sampleApiResponse = {
    code: 200,
    status: {
      id: "12345",
      url: "https://x.com/user/status/12345",
      text: "Wire test post",
      created_at: "2026-08-22T00:00:00Z",
      author: {
        id: "a1",
        screen_name: "testuser",
        name: "Test User",
      },
    },
  };

  test("runCommand fetch makes exact request and attaches provenance", async () => {
    let capturedRequestUrl = "";
    let capturedHeaders: Record<string, string> = {};

    const testClient = makeFxTwitterClient(
      HttpClient.make((request) => {
        capturedRequestUrl = request.url;
        capturedHeaders = Object.fromEntries(
          Object.entries(request.headers).map(([k, v]) => [k.toLowerCase(), String(v)])
        );
        return Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response(JSON.stringify(sampleApiResponse), {
              status: 200,
              headers: { "content-type": "application/json" },
            })
          )
        );
      }),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "fetch",
      target: "12345",
      lang: "en",
    }).pipe(Effect.provide(testLayer));

    const result = await Effect.runPromise(program);

    expect(capturedRequestUrl).toBe("https://api.fxtwitter.com/2/status/12345?lang=en");
    expect(capturedHeaders["accept"]).toBe("application/json");
    expect(capturedHeaders["user-agent"]).toBe("x-research/1");

    expect(result["requested_id"]).toBe("12345");
    expect(result["provider"]).toBe("fxtwitter");
    expect(result["official"]).toBe(false);
    expect(result["auth_mode"]).toBe("none");
    expect(result["provider_status"]).toBe(200);
    expect((result["post"] as Record<string, unknown>)["id"]).toBe("12345");
  });

  test("runCommand user-posts builds exact endpoint, query, and includes replies when set", async () => {
    let capturedUrl = "";
    const pagePayload = {
      code: 200,
      results: [sampleApiResponse.status],
      cursor: { bottom: "c1" },
    };

    const testClient = makeFxTwitterClient(
      HttpClient.make((request) => {
        capturedUrl = request.url;
        return Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response(JSON.stringify(pagePayload), {
              status: 200,
              headers: { "content-type": "application/json" },
            })
          )
        );
      }),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "user-posts",
      handle: "elonmusk",
      count: 10,
      includeReplies: true,
      cursor: "prev_cur",
    }).pipe(Effect.provide(testLayer));

    const result = await Effect.runPromise(program);

    expect(capturedUrl).toBe(
      "https://api.fxtwitter.com/2/profile/elonmusk/statuses?count=10&groupthreads=0&cursor=prev_cur&with_replies=1"
    );
    expect(result["handle"]).toBe("elonmusk");
    expect(result["requested_count"]).toBe(10);
    expect(result["returned_count"]).toBe(1);
    expect(result["cursor"]).toBe("c1");
  });

  test("runCommand search normalizes whitespace and query parameters", async () => {
    let capturedUrl = "";
    const searchPayload = {
      code: 200,
      results: [sampleApiResponse.status],
    };

    const testClient = makeFxTwitterClient(
      HttpClient.make((request) => {
        capturedUrl = request.url;
        return Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response(JSON.stringify(searchPayload), {
              status: 200,
              headers: { "content-type": "application/json" },
            })
          )
        );
      }),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "search",
      query: "OpenAI   release   since:2026-08-01",
      count: 15,
      feed: "latest",
    }).pipe(Effect.provide(testLayer));

    const result = await Effect.runPromise(program);

    expect(capturedUrl).toBe(
      "https://api.fxtwitter.com/2/search?q=OpenAI+release+since%3A2026-08-01&count=15&feed=latest"
    );
    expect(result["query"]).toBe("OpenAI release since:2026-08-01");
    expect(result["feed"]).toBe("latest");
  });

  test("runCommand conversation builds exact ranking mode and endpoint", async () => {
    let capturedUrl = "";
    const convPayload = {
      status: sampleApiResponse.status,
      thread: [],
      replies: [],
    };

    const testClient = makeFxTwitterClient(
      HttpClient.make((request) => {
        capturedUrl = request.url;
        return Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response(JSON.stringify(convPayload), {
              status: 200,
              headers: { "content-type": "application/json" },
            })
          )
        );
      }),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "conversation",
      id: "998877",
      rankingMode: "recency",
    }).pipe(Effect.provide(testLayer));

    const result = await Effect.runPromise(program);

    expect(capturedUrl).toBe("https://api.fxtwitter.com/2/conversation/998877?ranking_mode=recency");
    expect(result["requested_id"]).toBe("998877");
    expect(result["ranking_mode"]).toBe("recency");
  });

  test("HTTP error returns ProviderError with http_status without leaking body", async () => {
    const testClient = makeFxTwitterClient(
      HttpClient.make((request) =>
        Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response("Error body", { status: 404 })
          )
        )
      ),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "fetch",
      target: "99999",
    }).pipe(Effect.provide(testLayer));

    let errorCaught: unknown;
    try {
      await Effect.runPromise(program);
    } catch (err) {
      errorCaught = err;
    }

    expect(errorCaught).toBeInstanceOf(ProviderError);
    const pErr = errorCaught as ProviderError;
    expect(pErr.code).toBe("http_error");
    expect(pErr.details["http_status"]).toBe(404);
  });

  test("Malformed JSON body returns invalid_json ProviderError", async () => {
    const testClient = makeFxTwitterClient(
      HttpClient.make((request) =>
        Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response("<html>Not JSON</html>", { status: 200 })
          )
        )
      ),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "fetch",
      target: "12345",
    }).pipe(Effect.provide(testLayer));

    let errorCaught: unknown;
    try {
      await Effect.runPromise(program);
    } catch (err) {
      errorCaught = err;
    }

    expect(errorCaught).toBeInstanceOf(ProviderError);
    const pErr = errorCaught as ProviderError;
    expect(pErr.code).toBe("invalid_json");
  });

  test("API error status code (>= 400) maps to provider_error", async () => {
    const errorPayload = {
      code: 404,
      message: "Tweet not found",
    };

    const testClient = makeFxTwitterClient(
      HttpClient.make((request) =>
        Effect.succeed(
          HttpClientResponse.fromWeb(
            request,
            new Response(JSON.stringify(errorPayload), { status: 200 })
          )
        )
      ),
      DEFAULT_BASE_URL
    );

    const testLayer = Layer.succeed(FxTwitterClient, testClient);

    const program = runCommand({
      command: "fetch",
      target: "12345",
    }).pipe(Effect.provide(testLayer));

    let errorCaught: unknown;
    try {
      await Effect.runPromise(program);
    } catch (err) {
      errorCaught = err;
    }

    expect(errorCaught).toBeInstanceOf(ProviderError);
    const pErr = errorCaught as ProviderError;
    expect(pErr.code).toBe("provider_error");
    expect(pErr.details["provider_status"]).toBe(404);
  });
});

describe("CLI Entrypoint Subprocess Tests", () => {
  const cliPath = new URL("../scripts/cli.ts", import.meta.url).pathname;

  test("CLI rejects invalid inputs without network and exits code 2 with JSON envelope on stderr", async () => {
    const proc = Bun.spawn(["bun", cliPath, "fetch", "not-a-valid-target"], {
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    const stderrText = await new Response(proc.stderr).text();
    const stdoutText = await new Response(proc.stdout).text();

    expect(exitCode).toBe(2);
    expect(stdoutText.trim()).toBe("");
    expect(stderrText.trim()).not.toBe("");

    const errObj = JSON.parse(stderrText);
    expect(errObj.ok).toBe(false);
    expect(errObj.schema_version).toBe(SCHEMA_VERSION);
    expect(errObj.command).toBe("fetch");
    expect(errObj.error.code).toBe("invalid_target");
  });

  test("CLI usage error with --pretty emits indented JSON on stderr with exit 2", async () => {
    const proc = Bun.spawn(["bun", cliPath, "user-posts", "@InvalidHandle!", "--pretty"], {
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    const stderrText = await new Response(proc.stderr).text();

    expect(exitCode).toBe(2);
    expect(stderrText).toContain("\n  ");
    const errObj = JSON.parse(stderrText);
    expect(errObj.ok).toBe(false);
    expect(errObj.command).toBe("user-posts");
    expect(errObj.error.code).toBe("invalid_handle");
  });

  test("CLI --help exits 0 with human-readable help and no failure JSON", async () => {
    const proc = Bun.spawn(["bun", cliPath, "--help"], {
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    const stdoutText = await new Response(proc.stdout).text();
    const stderrText = await new Response(proc.stderr).text();

    expect(exitCode).toBe(0);
    expect(stderrText.trim()).toBe("");
    expect(stdoutText).toContain("fetch");
    expect(stdoutText).toContain("user-posts");
    expect(stdoutText).toContain("search");
    expect(stdoutText).toContain("conversation");
    expect(() => JSON.parse(stdoutText)).toThrow();
  });
});
