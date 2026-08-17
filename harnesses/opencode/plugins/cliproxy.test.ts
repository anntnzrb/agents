import { expect, test } from "bun:test";
import { mergeOpenCodeModels, type OpenCodeCatalogModel } from "./cliproxy.ts";

test("preserves fetched efforts and resolves the max policy", () => {
  const models = mergeOpenCodeModels(
    [catalogModel("go/deepseek-next", ["low", "high", "max", "ultra"])],
    {},
  );

  expect(models["go/deepseek-next"]).toMatchObject({
    reasoning: true,
    variants: {
      low: { reasoningEffort: "low" },
      high: { reasoningEffort: "high" },
      max: { reasoningEffort: "ultra" },
      ultra: { reasoningEffort: "ultra" },
    },
  });
});

test("preserves configured model options and variants", () => {
  const models = mergeOpenCodeModels([catalogModel("chatgpt/sol", ["low", "high"])], {
    "chatgpt/sol": {
      name: "Configured Sol",
      options: { textVerbosity: "low" },
      variants: {
        high: { reasoningEffort: "high", reasoningSummary: "detailed" },
        custom: { reasoningEffort: "low" },
      },
    },
    "local/custom": { name: "Local Custom" },
  });

  expect(models["chatgpt/sol"]).toMatchObject({
    name: "Configured Sol",
    options: { textVerbosity: "low" },
    variants: {
      low: { reasoningEffort: "low" },
      high: { reasoningEffort: "high", reasoningSummary: "detailed" },
      max: { reasoningEffort: "high" },
      custom: { reasoningEffort: "low" },
    },
  });
  expect(models["local/custom"]).toEqual({ name: "Local Custom" });
});

function catalogModel(
  id: string,
  reasoningEfforts: OpenCodeCatalogModel["reasoningEfforts"],
): OpenCodeCatalogModel {
  return {
    id,
    name: id,
    reasoning: true,
    ...(reasoningEfforts ? { reasoningEfforts } : {}),
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 16384,
  };
}
