import { expect, test } from "bun:test";
import {
  mergeOpenCodeModels,
  type OpenCodeCatalogModel,
} from "../../harnesses/opencode/plugins/cliproxy.ts";
import { piThinkingLevelMap } from "../../harnesses/pi/agent/extensions/cliproxy/thinking-levels.ts";

test("opencode_cliproxy_models_preserve_fetched_efforts_and_resolve_max_policy", () => {
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

test("pi_cliproxy_models_project_fetched_efforts_at_the_closed_harness_boundary", () => {
  expect(piThinkingLevelMap(["low", "high", "max", "ultra"])).toEqual({
    off: null,
    minimal: null,
    low: "low",
    medium: null,
    high: "high",
    xhigh: null,
    max: "ultra",
  });
});

test("opencode_cliproxy_models_preserve_configured_options_and_variants", () => {
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
