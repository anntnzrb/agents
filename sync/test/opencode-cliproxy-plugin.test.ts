import { expect, test } from "bun:test";
import {
  mergeOpenCodeModels,
  type OpenCodeCatalogModel,
} from "../../harnesses/opencode/plugins/cliproxy.ts";

test("opencode_cliproxy_models_expose_clamped_reasoning_variants", () => {
  const models = mergeOpenCodeModels(
    [catalogModel("go/deepseek-next", { low: "low", high: "high", max: "max" })],
    {},
  );

  expect(models["go/deepseek-next"]).toMatchObject({
    reasoning: true,
    variants: {
      minimal: { reasoningEffort: "low" },
      low: { reasoningEffort: "low" },
      medium: { reasoningEffort: "low" },
      high: { reasoningEffort: "high" },
      xhigh: { reasoningEffort: "high" },
      max: { reasoningEffort: "max" },
    },
  });
});

test("opencode_cliproxy_models_preserve_configured_options_and_variants", () => {
  const models = mergeOpenCodeModels([catalogModel("chatgpt/sol", { low: "low", high: "high" })], {
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
      minimal: { reasoningEffort: "low" },
      high: { reasoningEffort: "high", reasoningSummary: "detailed" },
      max: { reasoningEffort: "high" },
      custom: { reasoningEffort: "low" },
    },
  });
  expect(models["local/custom"]).toEqual({ name: "Local Custom" });
});

function catalogModel(
  id: string,
  thinkingLevelMap: OpenCodeCatalogModel["thinkingLevelMap"],
): OpenCodeCatalogModel {
  return {
    id,
    name: id,
    reasoning: true,
    ...(thinkingLevelMap ? { thinkingLevelMap } : {}),
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 16384,
  };
}
