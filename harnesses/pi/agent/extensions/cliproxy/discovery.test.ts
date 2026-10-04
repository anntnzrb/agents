import { expect, mock, spyOn, test } from "bun:test";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext, ProviderConfig, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

// Catalog discovery does not need Pi's bundled request-dialect metadata.
mock.module("@earendil-works/pi-ai/providers/all", () => ({
  getBuiltinProviders: () => [],
  getBuiltinModels: () => [],
  getBuiltinClassifierModels: () => [],
}));

test("refreshes missing metadata in a fresh cache, throttles retries, and retains cached data on failure", async () => {
  const directory = await mkdtemp(join(tmpdir(), "cliproxy-discovery-"));
  const previousCacheHome = process.env.XDG_CACHE_HOME;
  const previousOffline = process.env.PI_OFFLINE;
  process.env.XDG_CACHE_HOME = directory;
  delete process.env.PI_OFFLINE;
  let now = Date.now();
  const clock = spyOn(Date, "now").mockImplementation(() => now);
  const path = join(directory, "agents/models-dev.json");
  await mkdir(join(directory, "agents"));
  const known = { limit: { context: 200000, output: 32000 } };
  await writeFile(path, JSON.stringify({
    version: 2, fetchedAt: now, models: { known }, suffixes: { known }, stripped: { known },
  }));
  let ids = ["known"];
  let catalogRequests = 0;
  let failure = false;
  // Bun's fetch type adds preconnect, which the mock does not need.
  const network = spyOn(globalThis as { fetch: (url: URL | RequestInfo) => Promise<Response> }, "fetch").mockImplementation(async (url) => {
    if (String(url).endsWith("/models")) {
      return Response.json({ data: ids.map((id) => ({ id, owned_by: "openai" })) });
    }
    expect(String(url)).toBe("https://models.dev/api.json");
    catalogRequests++;
    if (failure) throw new Error("catalog unavailable");
    return Response.json({ openai: { models: {
      known,
      "gpt-6.1-sol": { limit: { context: 1050000, output: 128000 } },
    } } });
  });
  try {
    const { default: cliproxy } = await import("./index.ts");
    let config!: ProviderConfig;
    const handlers = new Map<string, (event: { model?: ExtensionContext["model"] }, ctx: ExtensionContext) => void>();
    await cliproxy({
      registerProvider: (_name: string, value: ProviderConfig) => { config = value; },
      on: (name: string, handler: (event: { model?: ExtensionContext["model"] }, ctx: ExtensionContext) => void) => {
        handlers.set(name, handler);
        return () => {};
      },
    } as unknown as ExtensionAPI);
    // cliproxy registers chat models only.
    const refresh = async () => (await config.refreshModels!({ signal: new AbortController().signal, allowNetwork: true, publish: async () => true } as Parameters<NonNullable<ProviderConfig["refreshModels"]>>[0])) as Extract<ProviderModelConfig, { type?: "chat" }>[];
    expect((await refresh())[0]?.contextWindow).toBe(200000);
    expect(catalogRequests).toBe(0);

    ids = ["gpt-6.1-sol"];
    expect((await refresh())[0]?.contextWindow).toBe(1050000);
    expect((await refresh())[0]?.maxTokens).toBe(128000);
    expect(catalogRequests).toBe(1);
    expect(JSON.parse(await readFile(path, "utf8")).models["gpt-6.1-sol"].limit.context).toBe(1050000);

    ids = ["unknown"];
    expect((await refresh())[0]?.contextWindow).toBe(128000);
    expect(catalogRequests).toBe(1);
    const warnings: string[] = [];
    const ctx = {
      hasUI: true, model: { id: "unknown", provider: "cliproxy" },
      ui: { notify: (message: string) => warnings.push(message) },
    } as unknown as ExtensionContext;
    handlers.get("session_start")!({}, { ...ctx, hasUI: false });
    handlers.get("model_select")!({ model: { ...ctx.model!, provider: "other" } }, ctx);
    expect(warnings).toHaveLength(0);
    handlers.get("session_start")!({}, ctx);
    handlers.get("model_select")!({ model: ctx.model }, ctx);
    handlers.get("before_agent_start")!({}, ctx);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("fallback");
    now += 60 * 60 * 1000;
    failure = true;
    expect((await refresh())[0]?.contextWindow).toBe(128000);
    expect(catalogRequests).toBe(2);
    await refresh();
    expect(catalogRequests).toBe(2);
    ids = ["gpt-6.1-sol"];
    expect((await refresh())[0]?.contextWindow).toBe(1050000);
    const aborted = new AbortController();
    aborted.abort();
    await config.refreshModels!({ signal: aborted.signal, allowNetwork: true, publish: async () => true } as Parameters<NonNullable<ProviderConfig["refreshModels"]>>[0]);
    expect(catalogRequests).toBe(2);

    process.env.PI_OFFLINE = "1";
    now += 60 * 60 * 1000;
    ids = ["unknown"];
    await refresh();
    expect(catalogRequests).toBe(2);
  } finally {
    network.mockRestore();
    clock.mockRestore();
    if (previousCacheHome === undefined) delete process.env.XDG_CACHE_HOME;
    else process.env.XDG_CACHE_HOME = previousCacheHome;
    if (previousOffline === undefined) delete process.env.PI_OFFLINE;
    else process.env.PI_OFFLINE = previousOffline;
    await rm(directory, { recursive: true, force: true });
  }
});
