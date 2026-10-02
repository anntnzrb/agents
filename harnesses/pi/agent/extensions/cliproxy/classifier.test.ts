import { expect, mock, test } from "bun:test";
import type { ExtensionAPI, ProviderConfig, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

const jev = {
  type: "classifier",
  id: "typesafe/jev-1.13",
  name: "TypeSafe: Jev 1.13",
  api: "typesafe-system-one",
  provider: "openrouter",
  baseUrl: "https://openrouter.ai/api/v1",
  input: ["text"],
  cost: { input: 0.042, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 32000,
};

mock.module("@earendil-works/pi-ai/providers/all", () => ({
  getBuiltinProviders: () => [],
  getBuiltinModels: () => [],
  getBuiltinClassifierModels: (provider: string) => (provider === "openrouter" ? [jev] : []),
}));

type ClassifierConfig = Extract<ProviderModelConfig, { type: "classifier" }>;
const classifiers = (models: readonly ProviderModelConfig[] | undefined): ClassifierConfig[] =>
  (models ?? []).filter((model): model is ClassifierConfig => model.type === "classifier");

test("registers the facade's System One classifiers and keeps them across catalog refreshes", async () => {
  // Offline refresh returns the last chat catalog plus classifiers without touching the module's
  // shared catalog state, which discovery.test.ts asserts on.
  const previousOffline = process.env.PI_OFFLINE;
  process.env.PI_OFFLINE = "1";
  try {
    const { default: cliproxy } = await import("./index.ts");
    let config!: ProviderConfig;
    cliproxy({
      registerProvider: (_name: string, value: ProviderConfig) => { config = value; },
      on: () => () => {},
    } as unknown as ExtensionAPI);

    const [registered] = classifiers(config.models);
    expect(registered).toMatchObject({
      type: "classifier",
      id: "typesafe/jev-1.13",
      api: "typesafe-system-one",
      contextWindow: 32000,
      cost: { input: 0.042, output: 0 },
    });
    // The model inherits the gateway endpoint; the transport appends `/systemone`.
    expect(registered?.baseUrl).toBeUndefined();
    expect(typeof config.classifiers?.["typesafe-system-one"]?.classify).toBe("function");

    const refreshed = await config.refreshModels!({ signal: new AbortController().signal } as Parameters<NonNullable<ProviderConfig["refreshModels"]>>[0]);
    expect(classifiers(refreshed).map((model) => model.id)).toEqual(["typesafe/jev-1.13"]);
  } finally {
    if (previousOffline === undefined) delete process.env.PI_OFFLINE;
    else process.env.PI_OFFLINE = previousOffline;
  }
});
