import { expect, spyOn, test } from "bun:test";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import type { ExtensionAPI, ExtensionContext, ProviderConfig, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

type RefreshContext = Parameters<NonNullable<ProviderConfig["refreshModels"]>>[0];
type ChatModel = Extract<ProviderModelConfig, { type?: "chat" }>;

const context = (allowNetwork: boolean): RefreshContext =>
  ({ allowNetwork, signal: new AbortController().signal, publish: async () => true }) as unknown as RefreshContext;

// Each Pi process loads the extension once; a query string gives every load a fresh module.
async function loadProvider(
  process: string,
  handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => void>(),
): Promise<ProviderConfig> {
  const { default: cliproxy } = await import(`./index.ts?process=${process}`);
  let config!: ProviderConfig;
  await cliproxy({
    registerProvider: (_name: string, value: ProviderConfig) => { config = value; },
    on: (name: string, handler: (event: unknown, ctx: ExtensionContext) => void) => {
      handlers.set(name, handler);
      return () => {};
    },
  } as unknown as ExtensionAPI);
  return config;
}

async function withGateway(
  run: (gateway: { models: unknown[]; catalog: unknown; up: boolean; status: number; requests: number }, cacheFile: string) => Promise<void>,
): Promise<void> {
  const directory = await mkdtemp(join(tmpdir(), "cliproxy-catalog-"));
  const previousCacheHome = process.env.XDG_CACHE_HOME;
  const previousOffline = process.env.PI_OFFLINE;
  process.env.XDG_CACHE_HOME = directory;
  delete process.env.PI_OFFLINE;
  const gateway = { models: [] as unknown[], catalog: {} as unknown, up: true, status: 200, requests: 0 };
  const network = spyOn(globalThis as { fetch: (url: URL | RequestInfo) => Promise<Response> }, "fetch").mockImplementation(async (url) => {
    if (String(url).endsWith("/models")) {
      gateway.requests++;
      if (!gateway.up) throw new Error("gateway unreachable");
      return Response.json({ data: gateway.models }, { status: gateway.status });
    }
    return Response.json(gateway.catalog);
  });
  try {
    await run(gateway, join(directory, "agents", "cliproxy-models.json"));
  } finally {
    network.mockRestore();
    if (previousCacheHome === undefined) delete process.env.XDG_CACHE_HOME;
    else process.env.XDG_CACHE_HOME = previousCacheHome;
    if (previousOffline === undefined) delete process.env.PI_OFFLINE;
    else process.env.PI_OFFLINE = previousOffline;
    await rm(directory, { recursive: true, force: true });
  }
}

const ids = (models: readonly ProviderModelConfig[]): string[] => models.map((model) => model.id);

test("Pi owns an atomic catalog cache and example-xhigh maps to example", async () => {
  await withGateway(async (gateway, cacheFile) => {
    const directory = dirname(cacheFile);
    await mkdir(directory, { recursive: true });
    const shared = join(directory, "models-dev.json");
    const owned = join(directory, "models-dev-pi.json");
    await writeFile(shared, "untouched");
    await writeFile(owned, "{}");
    const inode = (await stat(owned)).ino;
    gateway.models = [{ id: "example" }];
    gateway.catalog = { vendor: { models: { "example-xhigh": { limit: { context: 123456 } } } } };
    const models = await (await loadProvider("private-cache")).refreshModels!(context(true)) as ChatModel[];
    expect(models.find((model) => model.id === "example")?.contextWindow).toBe(123456);
    expect(await readFile(shared, "utf8")).toBe("untouched");
    expect((await stat(owned)).ino).not.toBe(inode);
    expect(JSON.parse(await readFile(owned, "utf8")).stripped.example.limit.context).toBe(123456);
    expect((await readdir(directory)).filter((name) => name.endsWith(".tmp"))).toEqual([]);
  });
});

test("a new process lists the cached catalog in Pi's cache-only phase, before any request", async () => {
  await withGateway(async (gateway, cacheFile) => {
    gateway.models = [{ id: "pool/vendor/alpha" }, { id: "pool/vendor/beta" }];
    const first = await loadProvider("cache-first");
    const offline = ids(await first.refreshModels!(context(false)));
    expect(offline).not.toContain("pool/vendor/alpha");
    expect(offline).toContain("devin/swe-2");
    expect(gateway.requests).toBe(0);
    expect(ids(await first.refreshModels!(context(true)))).toEqual(
      expect.arrayContaining(["pool/vendor/alpha", "pool/vendor/beta"]),
    );
    expect(JSON.parse(await readFile(cacheFile, "utf8")).models.map((model: { id: string }) => model.id)).toEqual(
      ["pool/vendor/alpha", "pool/vendor/beta"],
    );

    gateway.requests = 0;
    const second = await loadProvider("cache-second");
    // Registration carries the cache: Pi rebuilds providers from their registered models when
    // RPC mode starts, so a catalog only published by a refresh disappears until the next one.
    expect(ids(second.models ?? [])).toEqual(expect.arrayContaining(["pool/vendor/alpha", "pool/vendor/beta"]));
    expect(ids(await second.refreshModels!(context(false)))).toEqual(
      expect.arrayContaining(["pool/vendor/alpha", "pool/vendor/beta"]),
    );
    expect(gateway.requests).toBe(0);
  });
});

test("an unreachable gateway keeps the cached catalog", async () => {
  await withGateway(async (gateway) => {
    gateway.models = [{ id: "pool/vendor/alpha" }];
    await (await loadProvider("outage-first")).refreshModels!(context(true));
    gateway.up = false;
    const next = await loadProvider("outage-second");
    expect(ids(await next.refreshModels!(context(true)))).toContain("pool/vendor/alpha");
  });
});

test("startup rejects catalogs from another endpoint, expired catalogs, and malformed models", async () => {
  await withGateway(async (gateway, cacheFile) => {
    gateway.models = [{ id: "pool/vendor/alpha" }];
    await (await loadProvider("validation-first")).refreshModels!(context(true));
    const cache = JSON.parse(await readFile(cacheFile, "utf8"));
    for (const [label, invalid] of [
      ["endpoint", { ...cache, baseUrl: "http://another-gateway/v1" }],
      ["expired", { ...cache, fetchedAt: Date.now() - 8 * 24 * 60 * 60 * 1000 }],
      ["malformed", { ...cache, models: [null] }],
      ["input", { ...cache, models: [{ ...cache.models[0], input: null }] }],
      ["cost", { ...cache, models: [{ ...cache.models[0], cost: {} }] }],
      ["foreign-api", { ...cache, models: [{ ...cache.models[0], api: "openai-responses" }] }],
    ] as const) {
      await writeFile(cacheFile, JSON.stringify(invalid));
      const next = await loadProvider(`invalid-${label}`);
      expect(ids(next.models ?? [])).not.toContain("pool/vendor/alpha");
      expect(ids(await next.refreshModels!(context(false)))).not.toContain("pool/vendor/alpha");
    }
  });
});

test("a model missing from one listing stays available until it misses three in a row", async () => {
  await withGateway(async (gateway) => {
    const provider = await loadProvider("flap");
    gateway.models = [{ id: "pool/vendor/alpha" }, { id: "pool/vendor/flaky" }];
    await provider.refreshModels!(context(true));
    gateway.models = [{ id: "pool/vendor/alpha" }];
    expect(ids(await provider.refreshModels!(context(true)))).toContain("pool/vendor/flaky");
    expect(ids(await provider.refreshModels!(context(true)))).toContain("pool/vendor/flaky");
    expect(ids(await provider.refreshModels!(context(true)))).not.toContain("pool/vendor/flaky");
  });
});

test("brief-gap retention survives a restart without resetting the missing-listing count", async () => {
  await withGateway(async (gateway) => {
    gateway.models = [{ id: "pool/vendor/alpha" }, { id: "pool/vendor/flaky" }];
    const first = await loadProvider("restart-flap-first");
    await first.refreshModels!(context(true));
    gateway.models = [{ id: "pool/vendor/alpha" }];
    await first.refreshModels!(context(true));
    const second = await loadProvider("restart-flap-second");
    expect(ids(second.models ?? [])).toContain("pool/vendor/flaky");
    expect(ids(await second.refreshModels!(context(true)))).toContain("pool/vendor/flaky");
    expect(ids(await second.refreshModels!(context(true)))).not.toContain("pool/vendor/flaky");
  });
});

test("HTTP failures neither reset missing-model counts nor rewrite the persisted catalog", async () => {
  await withGateway(async (gateway, cacheFile) => {
    gateway.models = [{ id: "pool/vendor/alpha" }, { id: "pool/vendor/flaky" }];
    const provider = await loadProvider("http-failure");
    await provider.refreshModels!(context(true));
    gateway.models = [{ id: "pool/vendor/alpha" }];
    await provider.refreshModels!(context(true));
    const before = await readFile(cacheFile, "utf8");
    gateway.status = 503;
    expect(ids(await provider.refreshModels!(context(true)))).toContain("pool/vendor/flaky");
    expect(await readFile(cacheFile, "utf8")).toBe(before);
    gateway.status = 200;
    expect(ids(await provider.refreshModels!(context(true)))).toContain("pool/vendor/flaky");
    expect(ids(await provider.refreshModels!(context(true)))).not.toContain("pool/vendor/flaky");
  });
});

test("cached fallback models still warn when offline", async () => {
  await withGateway(async (gateway) => {
    gateway.models = [{ id: "pool/vendor/bare" }];
    await (await loadProvider("cached-warning-first")).refreshModels!(context(true));
    const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => void>();
    await loadProvider("cached-warning-second", handlers);
    const warnings: string[] = [];
    handlers.get("session_start")!({}, {
      hasUI: true,
      model: { id: "pool/vendor/bare", provider: "cliproxy" },
      ui: { notify: (message: string) => warnings.push(message) },
    } as unknown as ExtensionContext);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("fallback");
  });
});

test("the gateway's context_length fills limits the metadata catalog lacks", async () => {
  await withGateway(async (gateway) => {
    gateway.models = [{ id: "pool/vendor/unknown", context_length: 262144 }, { id: "pool/vendor/bare" }];
    const models = (await (await loadProvider("limits")).refreshModels!(context(true))) as ChatModel[];
    const byId = new Map(models.map((model) => [model.id, model]));
    expect(byId.get("pool/vendor/unknown")?.contextWindow).toBe(262144);
    expect(byId.get("pool/vendor/bare")?.contextWindow).toBe(128000);
  });
});

test("zero catalog limits cannot poison the startup cache for every gateway model", async () => {
  await withGateway(async (gateway, cacheFile) => {
    const image = { limit: { context: 0, output: 0 }, reasoning: false };
    gateway.catalog = { images: { models: { "image-model": image } } };
    await mkdir(dirname(cacheFile), { recursive: true });
    await writeFile(join(dirname(cacheFile), "models-dev-pi.json"), JSON.stringify({
      version: 2, fetchedAt: Date.now(),
      models: { "image-model": image }, suffixes: { "image-model": image }, stripped: { "image-model": image },
    }));
    gateway.models = [{ id: "image-model", context_length: 65536 }, { id: "pool/vendor/alpha" }];
    const first = await loadProvider("zero-limits-first");
    const models = await first.refreshModels!(context(true)) as ChatModel[];
    expect(models.find((model) => model.id === "image-model")).toMatchObject({
      contextWindow: 65536, maxTokens: 16384,
    });
    const second = await loadProvider("zero-limits-second");
    expect(ids(second.models ?? [])).toEqual(expect.arrayContaining(["image-model", "pool/vendor/alpha"]));
  });
});

test("Claude models the gateway serves natively use Anthropic Messages at the origin", async () => {
  await withGateway(async (gateway) => {
    gateway.models = [
      { id: "claude-opus-5-5", supported_endpoint_types: ["anthropic", "openai"] },
      { id: "claude-opus-5-5-high", supported_endpoint_types: ["openai"] },
      { id: "gpt-6.1-sol" },
    ];
    const models = (await (await loadProvider("routing")).refreshModels!(context(true))) as ChatModel[];
    const byId = new Map(models.map((model) => [model.id, model]));
    expect(byId.get("claude-opus-5-5")?.api).toBe("anthropic-messages");
    // Pi's Anthropic transport appends /v1/messages itself.
    expect(byId.get("claude-opus-5-5")?.baseUrl).not.toMatch(/\/v1$/);
    expect(byId.get("claude-opus-5-5")?.compat).toBeUndefined();
    expect(byId.get("claude-opus-5-5-high")?.api).toBeUndefined();
    expect(byId.get("gpt-6.1-sol")?.api).toBeUndefined();
    expect(byId.get("gpt-6.1-sol")?.baseUrl).toBeUndefined();
  });
});
