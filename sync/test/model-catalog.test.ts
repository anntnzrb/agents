import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  type CatalogModel,
  enrichGatewayModels,
  type ModelCatalogSource,
  modelsForSource,
  readModelCatalog,
  writeModelCatalog,
} from "@core/model-catalog.ts";

const SOURCE = {
  id: "example",
  modelsDevProvider: "example",
  prefix: "example",
  baseUrl: "https://example.test/v1",
} as const satisfies ModelCatalogSource;

test("models_dev_metadata_routes_live_models_without_local model policies", () => {
  const result = modelsForSource(
    SOURCE,
    {
      data: [
        { id: "chat-next" },
        { id: "responses-next" },
        { id: "claude-next" },
        { id: "google-next" },
        { id: "no-tools" },
        { id: "not-in-metadata", context_length: 64000 },
      ],
    },
    {
      example: {
        npm: "@ai-sdk/openai-compatible",
        models: {
          "chat-next": modelMetadata("Chat Next"),
          "responses-next": {
            ...modelMetadata("Responses Next"),
            provider: { npm: "@ai-sdk/openai" },
          },
          "claude-next": {
            ...modelMetadata("Claude Next"),
            provider: { npm: "@ai-sdk/anthropic" },
          },
          "google-next": {
            ...modelMetadata("Google Next"),
            provider: { npm: "@ai-sdk/google" },
          },
          "no-tools": {
            ...modelMetadata("No Tools"),
            tool_call: false,
          },
        },
      },
    },
  );

  expect([...result.groups.keys()]).toEqual([
    "anthropic-messages",
    "openai-completions",
    "openai-responses",
  ]);
  expect(result.unsupported).toEqual([
    {
      id: "google-next",
      npm: "@ai-sdk/google",
      shape: undefined,
    },
  ]);
  expect(result.models.map((model) => model.id)).toEqual([
    "example/chat-next",
    "example/claude-next",
    "example/not-in-metadata",
    "example/responses-next",
  ]);
  expect(result.models.find((model) => model.id.endsWith("responses-next"))).toMatchObject({
    api: "openai-responses",
    reasoning: true,
    input: ["text", "image"],
    contextWindow: 300000,
    maxTokens: 100000,
  });
  expect(result.models.find((model) => model.id.endsWith("not-in-metadata"))).toMatchObject({
    api: "openai-completions",
    contextWindow: 64000,
  });
});

test("models_dev_shape_override_wins_over_npm_default", () => {
  const result = modelsForSource(
    SOURCE,
    { data: [{ id: "shape-completions" }, { id: "shape-responses" }] },
    {
      example: {
        npm: "@ai-sdk/openai",
        models: {
          "shape-completions": {
            ...modelMetadata("Completions"),
            provider: { shape: "completions" },
          },
          "shape-responses": {
            ...modelMetadata("Responses"),
            provider: { shape: "responses" },
          },
        },
      },
    },
  );

  expect(result.models).toMatchObject([
    { id: "example/shape-completions", api: "openai-completions" },
    { id: "example/shape-responses", api: "openai-responses" },
  ]);
});

test("rich_openai_catalog_fields_enrich_models_dev_metadata", () => {
  const result = modelsForSource(
    { ...SOURCE, id: "router", prefix: "router", modelsDevProvider: "router" },
    {
      data: [
        {
          id: "router/auto",
          name: "Auto Router",
          context_length: 2000000,
          architecture: {
            input_modalities: ["text", "image"],
            output_modalities: ["text"],
          },
          supported_parameters: ["tools", "reasoning", "tool_choice"],
          pricing: { prompt: "0.000001", completion: "0.000002" },
          top_provider: { max_completion_tokens: 64000 },
        },
      ],
    },
    {
      router: {
        npm: "@ai-sdk/openai-compatible",
        models: {
          "router/auto": modelMetadata("Catalog Name"),
        },
      },
    },
  );

  expect(result.models).toMatchObject([
    {
      id: "router/auto",
      name: "Auto Router",
      api: "openai-completions",
      reasoning: true,
      input: ["text", "image"],
      contextWindow: 2000000,
      maxTokens: 64000,
      cost: { input: 1, output: 2 },
    },
  ]);
});

test("gateway_catalog_adds_oauth_models_without_overwriting_richer_models", () => {
  const external = modelsForSource(
    SOURCE,
    { data: [{ id: "responses-next" }] },
    {
      example: {
        npm: "@ai-sdk/openai",
        models: {
          "responses-next": modelMetadata("Responses Next"),
        },
      },
    },
  ).models;

  const merged = enrichGatewayModels(
    external,
    {
      data: [
        { id: "example/responses-next", owned_by: "openai" },
        { id: "gpt-oauth-next", owned_by: "openai" },
        { id: "gemini-oauth-next", owned_by: "antigravity" },
        { id: "gpt-image-next", owned_by: "openai" },
      ],
    },
    {
      modelsDev: {
        openai: {
          npm: "@ai-sdk/openai",
          models: {
            "gpt-oauth-next": modelMetadata("GPT OAuth Next"),
          },
        },
      },
    },
  );

  expect(merged.map((model) => model.id)).toEqual([
    "example/responses-next",
    "gemini-oauth-next",
    "gpt-oauth-next",
  ]);
  expect(merged.find((model) => model.id === "example/responses-next")).toMatchObject({
    contextWindow: 300000,
  });
  expect(merged.find((model) => model.id === "gpt-oauth-next")).toMatchObject({
    api: "openai-responses",
    reasoning: true,
    contextWindow: 300000,
  });
});

function modelMetadata(name: string): Record<string, unknown> {
  return {
    id: name.toLowerCase().replaceAll(" ", "-"),
    name,
    reasoning: true,
    reasoning_options: [{ type: "effort", values: ["low", "high"] }],
    tool_call: true,
    modalities: { input: ["text", "image"], output: ["text"] },
    limit: { context: 300000, output: 100000 },
    cost: { input: 0.2, output: 0.8, cache_read: 0.02 },
  };
}

test("catalog_orders_models_by_codepoint_not_locale", () => {
  const root = mkdtempSync(join(tmpdir(), "catalog-order-test-"));
  try {
    const path = join(root, "catalog.json");
    writeModelCatalog(path, [
      catalogModel("zen/nemotron-3.5-lightning-free"),
      catalogModel("zen/nemotron-3-ultra-free"),
      catalogModel("zen/gpt-5.6-sol"),
    ]);
    expect(readModelCatalog(path).map((model) => model.id)).toEqual([
      "zen/gpt-5.6-sol",
      "zen/nemotron-3-ultra-free",
      "zen/nemotron-3.5-lightning-free",
    ]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

function catalogModel(id: string): CatalogModel {
  return {
    id,
    name: id,
    api: "openai-completions",
    reasoning: true,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 16384,
  };
}
