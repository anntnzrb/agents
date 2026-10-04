import { expect, spyOn, test } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ProviderConfig, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

type ClassifierConfig = Extract<ProviderModelConfig, { type: "classifier" }>;
const classifiers = (models: readonly ProviderModelConfig[] | undefined): ClassifierConfig[] =>
  (models ?? []).filter((model): model is ClassifierConfig => model.type === "classifier");

test("classifier discovery controls registration, persists offline, and applies removals", async () => {
  const directory = await mkdtemp(join(tmpdir(), "cliproxy-classifiers-"));
  const previousCache = process.env.XDG_CACHE_HOME;
  const previousOffline = process.env.PI_OFFLINE;
  process.env.XDG_CACHE_HOME = directory;
  delete process.env.PI_OFFLINE;
  let allowed = ["typesafe/jev-1.13", "unknown/classifier"];
  let status = 200;
  let requests = 0;
  const network = spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    expect(String(url)).toEndWith("/systemone/models");
    requests++;
    return Response.json({ data: allowed.map((id) => ({ id })) }, { status });
  });
  async function load(label: string): Promise<ProviderConfig> {
    const { default: cliproxy } = await import(`./index.ts?classifiers=${label}`);
    let config!: ProviderConfig;
    await cliproxy({ registerProvider: (_name: string, value: ProviderConfig) => { config = value; }, on: () => () => {} } as unknown as ExtensionAPI);
    return config;
  }
  const refresh = (config: ProviderConfig, allowNetwork: boolean) => config.refreshModels!({
    signal: new AbortController().signal, allowNetwork, publish: async () => true,
  } as Parameters<NonNullable<ProviderConfig["refreshModels"]>>[0]);
  try {
    const config = await load("first");
    expect(classifiers(config.models)).toEqual([]);
    // The chat edge can fail independently of classifier discovery.
    const models = classifiers(await refresh(config, true));
    expect(models).toHaveLength(1);
    expect(models[0]).toMatchObject({ id: "typesafe/jev-1.13", api: "typesafe-system-one", contextWindow: 32000 });
    expect(models[0].cost.input).toBeGreaterThan(0);
    expect(models[0].baseUrl).toBeUndefined();
    expect(typeof config.classifiers?.["typesafe-system-one"]?.classify).toBe("function");
    const cacheFile = join(directory, "agents", "cliproxy-classifiers-pi.json");
    const persisted = await readFile(cacheFile, "utf8");
    process.env.PI_OFFLINE = "1";
    const offline = await load("offline");
    expect(classifiers(offline.models).map((model) => model.id)).toEqual(["typesafe/jev-1.13"]);
    const count = requests;
    await refresh(offline, true);
    expect(requests).toBe(count);
    delete process.env.PI_OFFLINE;
    status = 503;
    expect(classifiers(await refresh(config, true))).toHaveLength(1);
    expect(await readFile(cacheFile, "utf8")).toBe(persisted);
    status = 200;
    allowed = [];
    expect(classifiers(await refresh(config, true))).toEqual([]);
    expect(classifiers((await load("removed")).models)).toEqual([]);
    for (const invalid of [
      { ...JSON.parse(persisted), baseUrl: "http://other/v1" },
      { ...JSON.parse(persisted), fetchedAt: Date.now() - 8 * 24 * 60 * 60 * 1000 },
      { ...JSON.parse(persisted), ids: [null] },
    ]) {
      await writeFile(cacheFile, JSON.stringify(invalid));
      expect(classifiers((await load(`invalid-${requests++}`)).models)).toEqual([]);
    }
  } finally {
    network.mockRestore();
    if (previousCache === undefined) delete process.env.XDG_CACHE_HOME;
    else process.env.XDG_CACHE_HOME = previousCache;
    if (previousOffline === undefined) delete process.env.PI_OFFLINE;
    else process.env.PI_OFFLINE = previousOffline;
    await rm(directory, { recursive: true, force: true });
  }
});
