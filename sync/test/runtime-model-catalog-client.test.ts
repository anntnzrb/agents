import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  parseModelCatalog,
  type RuntimeCatalogModel,
  readModelCatalog,
  resolveLiveModelCatalog,
} from "@runtime/model-catalog-client.ts";

test("installed_runtime_model_catalog_client_validates_and_projects_catalog", () => {
  const root = mkdtempSync(join(tmpdir(), "agents-runtime-catalog-test-"));
  try {
    const path = join(root, "catalog.json");
    writeFileSync(
      path,
      JSON.stringify({
        version: 1,
        models: [
          {
            id: "example/model",
            name: "Example",
            api: "openai-responses",
            reasoning: true,
            reasoningEfforts: ["low", "ultra"],
            defaultReasoningEffort: "low",
            input: ["text", "image"],
            cost: { input: 1, output: 2, cacheRead: 0.1, cacheWrite: 0 },
            contextWindow: 128000,
            maxTokens: 32000,
            compat: { ignoredByRuntimeProjection: true },
          },
          {
            id: "example/legacy",
            name: "Legacy",
            api: "openai-responses",
            reasoning: true,
            thinkingLevelMap: { low: "low", high: "high", max: null },
            input: ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 128000,
            maxTokens: 32000,
          },
          {
            id: "example/empty",
            name: "Empty",
            api: "openai-responses",
            reasoning: false,
            reasoningEfforts: [],
            input: ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 128000,
            maxTokens: 32000,
          },
        ],
      }),
    );

    const expected: readonly RuntimeCatalogModel[] = [
      {
        id: "example/model",
        name: "Example",
        reasoning: true,
        reasoningEfforts: ["low", "ultra"],
        defaultReasoningEffort: "low",
        input: ["text", "image"],
        cost: { input: 1, output: 2, cacheRead: 0.1, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 32000,
      },
      {
        id: "example/legacy",
        name: "Legacy",
        reasoning: true,
        reasoningEfforts: ["low", "high"],
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 32000,
      },
      {
        id: "example/empty",
        name: "Empty",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 32000,
      },
    ];

    expect(parseModelCatalog(readFileSync(path, "utf8"), path)).toEqual(expected);
    expect(readModelCatalog(path)).toEqual(expected);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("installed_runtime_model_catalog_client_uses_live metadata with local cost", async () => {
  const root = mkdtempSync(join(tmpdir(), "agents-runtime-live-catalog-test-"));
  try {
    const path = join(root, "catalog.json");
    const known = runtimeModel("cmd/known", "Cached", {
      cost: { input: 1, output: 2, cacheRead: 0.1, cacheWrite: 0.2 },
    });
    writeFileSync(path, JSON.stringify({ version: 1, models: [known, runtimeModel("old/model")] }));
    const calls: string[] = [];
    let request: RequestInit | undefined;

    const resolved = await resolveLiveModelCatalog({
      catalogPath: path,
      baseUrl: "https://gateway.example.test/v1",
      fetch: async (input, init) => {
        request = init;
        calls.push(
          typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
        );
        return Response.json({
          models: [
            liveModel(
              "cmd/known",
              "Live Known",
              1000000,
              64000,
              ["text", "image"],
              ["low", "high"],
              "low",
            ),
            liveModel("cmd/new", "Live New", 256000, 32000, ["text"], ["high", "max"], "high"),
          ],
        });
      },
    });

    expect(calls).toEqual(["https://gateway.example.test/v1/models?client_version"]);
    expect(request).toMatchObject({ cache: "no-store" });
    expect(resolved).toEqual([
      runtimeModel("cmd/known", "Live Known", {
        reasoning: true,
        reasoningEfforts: ["low", "high"],
        defaultReasoningEffort: "low",
        input: ["text", "image"],
        cost: known.cost,
        contextWindow: 1000000,
        maxTokens: 64000,
      }),
      runtimeModel("cmd/new", "Live New", {
        reasoning: true,
        reasoningEfforts: ["high", "max"],
        defaultReasoningEffort: "high",
        contextWindow: 256000,
        maxTokens: 32000,
      }),
    ]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("installed_runtime_model_catalog_client_uses_local_fallback_after_live_fetch_failure", async () => {
  const root = mkdtempSync(join(tmpdir(), "agents-runtime-live-fallback-test-"));
  try {
    const path = join(root, "catalog.json");
    const local = [runtimeModel("cmd/cached")];
    writeFileSync(path, JSON.stringify({ version: 1, models: local }));

    const resolved = await resolveLiveModelCatalog({
      catalogPath: path,
      baseUrl: "https://gateway.example.test/v1",
      fetch: async () => {
        throw new Error("gateway unavailable");
      },
    });
    expect(resolved).toEqual(local);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("installed_runtime_model_catalog_client_can_resolve_live_models_without_local_state", async () => {
  const root = mkdtempSync(join(tmpdir(), "agents-runtime-live-only-test-"));
  try {
    const resolved = await resolveLiveModelCatalog({
      catalogPath: join(root, "missing.json"),
      baseUrl: "https://gateway.example.test/v1",
      fetch: async () =>
        Response.json({
          models: [liveModel("cmd/live", "Live", 1000000, 64000, ["text"], ["low"], "low")],
        }),
    });

    expect(resolved).toEqual([
      runtimeModel("cmd/live", "Live", {
        reasoning: true,
        reasoningEfforts: ["low"],
        defaultReasoningEffort: "low",
        contextWindow: 1000000,
        maxTokens: 64000,
      }),
    ]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

function liveModel(
  slug: string,
  displayName: string,
  contextWindow: number,
  maxTokens: number,
  input: readonly string[],
  efforts: readonly string[],
  defaultReasoningEffort: string,
): Record<string, unknown> {
  return {
    slug,
    display_name: displayName,
    context_window: contextWindow,
    input_modalities: input,
    supported_reasoning_levels: efforts.map((effort) => ({ effort })),
    default_reasoning_level: defaultReasoningEffort,
    truncation_policy: { limit: maxTokens, mode: "tokens" },
  };
}

function runtimeModel(
  id: string,
  name = id,
  overrides: Partial<RuntimeCatalogModel> = {},
): RuntimeCatalogModel {
  return {
    id,
    name,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 16384,
    ...overrides,
  };
}
