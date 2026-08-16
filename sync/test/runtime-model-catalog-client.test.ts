import { expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readModelCatalog } from "@runtime/model-catalog-client.ts";

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

    expect(readModelCatalog(path)).toEqual([
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
    ]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
