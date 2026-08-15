import { expect, test } from "bun:test";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  legacyModelCatalogPath,
  renderCliProxyConfig,
  runtimeClientApiKeyPath,
  runtimeModelCatalogPath,
  syncCliProxyConfig,
} from "@core/cliproxy-config.ts";
import { modelsForSource } from "@core/model-catalog.ts";

test("cliproxy_renderer_synthesizes_protocol_profiles_from_model_sources", () => {
  const source = {
    id: "example",
    modelsDevProvider: "example",
    prefix: "example",
    baseUrl: "https://example.test/v1",
  } as const;
  const discovered = modelsForSource(
    source,
    {
      data: [{ id: "chat-next" }, { id: "responses-next" }, { id: "claude-next" }],
    },
    {
      example: {
        npm: "@ai-sdk/openai-compatible",
        models: {
          "chat-next": metadata("Chat Next"),
          "responses-next": {
            ...metadata("Responses Next"),
            provider: { npm: "@ai-sdk/openai" },
          },
          "claude-next": {
            ...metadata("Claude Next"),
            provider: { npm: "@ai-sdk/anthropic" },
          },
        },
      },
    },
  );
  const rendered = renderCliProxyConfig(
    `remote-management:
  secret-key: \${CLIPROXY_MANAGEMENT_KEY}
api-keys: \${CLIPROXY_CLIENT_API_KEYS}
x-model-sources:
  - id: example
    models-dev-provider: example
    credential-pool: example
    prefix: example
    base-url: https://example.test/v1
`,
    {
      CLIPROXY_MANAGEMENT_KEY: "management",
      CLIPROXY_CLIENT_API_KEYS: ["client"],
      CLIPROXY_CREDENTIAL_POOLS: {
        example: [
          { apiKey: "one", weight: 1 },
          { apiKey: "two", weight: 2 },
        ],
      },
    },
    "management-hash",
    new Map([["example", discovered]]),
  );
  const config = Bun.YAML.parse(rendered) as Record<string, any>;

  expect(config["x-model-sources"]).toBeUndefined();
  expect(config["openai-compatibility"]).toHaveLength(1);
  expect(config["openai-compatibility"][0]).toMatchObject({
    name: "example",
    prefix: "example",
    "base-url": "https://example.test/v1",
    models: [{ name: "chat-next", alias: "chat-next" }],
    "api-key-entries": [
      { "api-key": "one", weight: 1 },
      { "api-key": "two", weight: 2 },
    ],
  });
  expect(config["codex-api-key"]).toHaveLength(2);
  expect(config["codex-api-key"][0]).toMatchObject({
    "api-key": "one",
    prefix: "example",
    "base-url": "https://example.test/v1",
    models: [{ name: "responses-next", alias: "responses-next" }],
  });
  expect(config["claude-api-key"]).toHaveLength(2);
  expect(config["claude-api-key"][0]).toMatchObject({
    "api-key": "one",
    prefix: "example",
    "base-url": "https://example.test",
    models: [{ name: "claude-next", alias: "claude-next" }],
  });
});

test("cliproxy_sync_discovers_once_then_reuses_fresh_catalog_cache", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-catalog-test-"));
  try {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "runtime", "config.yaml");
    const secretsPath = join(root, "secrets.json");
    const cacheRoot = join(root, "cache");
    const runtimeRoot = join(root, "data");
    mkdirSync(join(root, "runtime"), { recursive: true });
    mkdirSync(cacheRoot, { recursive: true });
    writeFileSync(legacyModelCatalogPath(cacheRoot), "legacy catalog\n");
    writeFileSync(
      src,
      `host: 127.0.0.1
port: 8317
tls:
  enable: false
remote-management:
  secret-key: \${CLIPROXY_MANAGEMENT_KEY}
api-keys: \${CLIPROXY_CLIENT_API_KEYS}
x-model-sources:
  - id: example
    models-dev-provider: example
    credential-pool: example
    prefix: example
    base-url: https://example.test/v1
`,
    );
    writeFileSync(
      secretsPath,
      `${JSON.stringify({
        CLIPROXY_MANAGEMENT_KEY: "management",
        CLIPROXY_CLIENT_API_KEYS: ["client"],
        CLIPROXY_CREDENTIAL_POOLS: {
          example: [{ apiKey: "upstream", weight: 1 }],
        },
      })}\n`,
    );
    const calls: string[] = [];
    const fetchImpl = async (input: string | URL | Request) => {
      const url =
        typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      calls.push(url);
      if (url === "https://models.dev/api.json") {
        return Response.json({
          example: {
            npm: "@ai-sdk/openai-compatible",
            models: { "chat-next": metadata("Chat Next") },
          },
        });
      }
      if (url === "https://example.test/v1/models") {
        return Response.json({ data: [{ id: "chat-next" }] });
      }
      if (url === "http://127.0.0.1:8317/v1/models") {
        return Response.json({
          data: [{ id: "oauth-next", owned_by: "example-oauth" }],
        });
      }
      return new Response(null, { status: 404 });
    };
    const options = {
      cacheRoot,
      runtimeRoot,
      forceModelRefresh: true,
      fetch: fetchImpl,
      now: () => 1000,
    };

    await syncCliProxyConfig(src, dst, secretsPath, options);
    expect(calls).toEqual([
      "https://models.dev/api.json",
      "https://example.test/v1/models",
      "http://127.0.0.1:8317/v1/models",
    ]);
    expect(Bun.YAML.parse(readFileSync(dst, "utf8"))).toMatchObject({
      "openai-compatibility": [
        {
          prefix: "example",
          models: [{ name: "chat-next", alias: "chat-next" }],
        },
      ],
    });
    const catalog = JSON.parse(readFileSync(runtimeModelCatalogPath(runtimeRoot), "utf8"));
    expect(catalog.models.map((model: { id: string }) => model.id)).toEqual([
      "example/chat-next",
      "oauth-next",
    ]);
    expect(existsSync(legacyModelCatalogPath(cacheRoot))).toBe(false);

    calls.length = 0;
    const configStat = lstatSync(dst);
    expect(readFileSync(runtimeClientApiKeyPath(runtimeRoot), "utf8")).toBe("client\n");
    expect(lstatSync(runtimeClientApiKeyPath(runtimeRoot)).mode & 0o777).toBe(0o600);
    const catalogStat = lstatSync(runtimeModelCatalogPath(runtimeRoot));
    await syncCliProxyConfig(src, dst, secretsPath, {
      ...options,
      forceModelRefresh: false,
      now: () => 1100,
    });
    expect(calls).toEqual([]);
    expect(lstatSync(dst).ino).toBe(configStat.ino);
    expect(lstatSync(runtimeModelCatalogPath(runtimeRoot)).ino).toBe(catalogStat.ino);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

function metadata(name: string): Record<string, unknown> {
  return {
    id: name.toLowerCase().replaceAll(" ", "-"),
    name,
    reasoning: true,
    tool_call: true,
    modalities: { input: ["text"], output: ["text"] },
    limit: { context: 200000, output: 64000 },
  };
}
