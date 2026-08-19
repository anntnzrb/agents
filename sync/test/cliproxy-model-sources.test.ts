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
import { join, resolve } from "node:path";
import {
  legacyModelCatalogPath,
  modelAliasesFromTemplate,
  modelSourcesFromTemplate,
  renderCliProxyConfig,
  runtimeModelCatalogPath,
  syncClientModelCatalog,
  syncCliProxyConfig,
} from "@core/cliproxy-config.ts";
import type { CliProxyDeployment } from "@core/cliproxy-deployment.ts";
import { modelsForSource } from "@core/model-catalog.ts";

const REPOSITORY_ROOT = resolve(import.meta.dir, "../..");

const DEPLOYMENT: CliProxyDeployment = {
  server: { hostname: "test-gateway" },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
};

test("cliproxy_committed_template_declares_command_code_and_resolvable_aliases", () => {
  const template = readFileSync(
    join(REPOSITORY_ROOT, "tools", "cliproxyapi", "config.yaml.tmpl"),
    "utf8",
  );

  expect(modelSourcesFromTemplate(template)).toContainEqual({
    id: "command-code",
    modelsDevProvider: "openrouter",
    credentialPool: "command-code",
    prefix: "cmd",
    baseUrl: "https://api.commandcode.ai/provider/v1",
  });
  expect(modelAliasesFromTemplate(template)).toContainEqual({
    id: "cmd/nnn-deepseek-v4-flash-max",
    sourceId: "cmd/deepseek/deepseek-v4-flash",
    name: "[nnn] DeepSeek V4 Flash (Max)",
  });
});

test("cliproxy_template_exposes_custom_compatibility_aliases to the shared catalog", () => {
  expect(
    modelAliasesFromTemplate(`openai-compatibility:
  - name: example-custom
    prefix: example
    models:
      - name: responses-next
        alias: nnn-responses-next-high
        display-name: "[nnn] Responses Next (High)"
      - name: unchanged
        alias: unchanged
`),
  ).toEqual([
    {
      id: "example/nnn-responses-next-high",
      sourceId: "example/responses-next",
      name: "[nnn] Responses Next (High)",
    },
  ]);
});

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
  allow-remote: true
x-model-sources:
  - id: example
    models-dev-provider: example
    credential-pool: example
    prefix: example
    base-url: https://example.test/v1
`,
    {
      CLIPROXY_CREDENTIAL_POOLS: {
        example: [
          { apiKey: "one", weight: 1 },
          { apiKey: "two", weight: 2 },
        ],
      },
    },
    DEPLOYMENT,
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
      `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
tls:
  enable: false
remote-management:
  allow-remote: true
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
      if (url === "https://gateway.example.test:9443/v1/models") {
        return Response.json({
          data: [{ id: "oauth-next", owned_by: "example-oauth" }],
        });
      }
      if (url === "https://gateway.example.test:9443/v1/models?client_version=0.144.1") {
        return Response.json({
          models: [
            {
              slug: "example/chat-next",
              display_name: "Chat Next Live",
              context_window: 256000,
              input_modalities: ["text"],
              supported_reasoning_levels: [{ effort: "low" }, { effort: "high" }],
            },
          ],
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

    await syncCliProxyConfig(src, dst, secretsPath, DEPLOYMENT, options);
    expect(calls).toEqual([
      "https://models.dev/api.json",
      "https://example.test/v1/models",
      "https://gateway.example.test:9443/v1/models",
      "https://gateway.example.test:9443/v1/models?client_version=0.144.1",
    ]);
    expect(Bun.YAML.parse(readFileSync(dst, "utf8"))).toMatchObject({
      host: DEPLOYMENT.listen.host,
      port: DEPLOYMENT.listen.port,
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
    expect(existsSync(join(runtimeRoot, "cliproxyapi", "client-api-key"))).toBe(false);
    const catalogStat = lstatSync(runtimeModelCatalogPath(runtimeRoot));
    await syncCliProxyConfig(src, dst, secretsPath, DEPLOYMENT, {
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

test("cliproxy_client_sync_preserves_server_config_and_drops_stale_client_key", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-client-config-test-"));
  try {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "runtime", "config.yaml");
    const secretsPath = join(root, "secrets.json");
    const runtimeRoot = join(root, "data");
    const staleKeyPath = join(runtimeRoot, "cliproxyapi", "client-api-key");
    mkdirSync(join(root, "runtime"), { recursive: true });
    mkdirSync(join(runtimeRoot, "cliproxyapi"), { recursive: true });
    writeFileSync(dst, "existing gateway config\n", { mode: 0o600 });
    writeFileSync(staleKeyPath, "stale-client-key\n", { mode: 0o600 });
    writeFileSync(
      src,
      "host: $" +
        "{CLIPROXY_LISTEN_HOST}\n" +
        "port: $" +
        "{CLIPROXY_LISTEN_PORT}\n" +
        "remote-management:\n" +
        "  allow-remote: true\n" +
        "codex-api-key:\n" +
        "  - x-credential-pool: fixture\n",
    );
    writeFileSync(
      secretsPath,
      `${JSON.stringify({
        CLIPROXY_CREDENTIAL_POOLS: { fixture: [{ apiKey: "upstream" }] },
      })}\n`,
    );

    await syncCliProxyConfig(src, dst, secretsPath, DEPLOYMENT, {
      runtimeRoot,
      writeServerConfig: false,
    });

    expect(readFileSync(dst, "utf8")).toBe("existing gateway config\n");
    expect(existsSync(staleKeyPath)).toBe(false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_client_catalog_syncs_from_gateway_models_without_secrets", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-client-catalog-test-"));
  try {
    const src = join(root, "config.yaml.tmpl");
    const cacheRoot = join(root, "cache");
    const runtimeRoot = join(root, "data");
    mkdirSync(cacheRoot, { recursive: true });
    const staleKeyPath = join(runtimeRoot, "cliproxyapi", "client-api-key");
    mkdirSync(join(runtimeRoot, "cliproxyapi"), { recursive: true });
    writeFileSync(staleKeyPath, "stale\n", { mode: 0o600 });
    writeFileSync(
      src,
      `x-model-sources:
  - id: example
    models-dev-provider: example
    credential-pool: example
    prefix: example
    base-url: https://example.test/v1
`,
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
            models: {
              "chat-next": {
                ...metadata("Chat Next"),
                cost: { input: 1, output: 2, cache_read: 3, cache_write: 4 },
              },
            },
          },
        });
      }
      if (url === "https://gateway.example.test:9443/v1/models") {
        return Response.json({
          data: [
            { id: "example/chat-next", owned_by: "example" },
            { id: "oauth-next", owned_by: "openai" },
          ],
        });
      }
      if (url === "https://gateway.example.test:9443/v1/models?client_version=0.144.1") {
        return Response.json({
          models: [
            {
              slug: "example/chat-next",
              display_name: "Chat Next Live",
              context_window: 256000,
              input_modalities: ["text", "image"],
              supported_reasoning_levels: [{ effort: "low" }, { effort: "high" }],
            },
          ],
        });
      }
      return new Response(null, { status: 404 });
    };

    await syncClientModelCatalog(src, DEPLOYMENT, {
      cacheRoot,
      runtimeRoot,
      forceModelRefresh: true,
      fetch: fetchImpl,
      now: () => 1000,
    });

    expect(calls).toEqual([
      "https://models.dev/api.json",
      "https://gateway.example.test:9443/v1/models",
      "https://gateway.example.test:9443/v1/models?client_version=0.144.1",
    ]);
    const catalog = JSON.parse(readFileSync(runtimeModelCatalogPath(runtimeRoot), "utf8"));
    expect(catalog.models.map((model: { id: string }) => model.id)).toEqual([
      "example/chat-next",
      "oauth-next",
    ]);
    expect(
      catalog.models.find((model: { id: string }) => model.id === "example/chat-next"),
    ).toMatchObject({
      name: "Chat Next Live",
      api: "openai-completions",
      reasoning: true,
      reasoningEfforts: ["low", "high"],
      input: ["text", "image"],
      contextWindow: 256000,
      maxTokens: 64000,
      cost: { input: 1, output: 2, cacheRead: 3, cacheWrite: 4 },
    });
    expect(existsSync(staleKeyPath)).toBe(false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_sync_discovers_models_from_a_custom_catalog_field", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-custom-catalog-test-"));
  try {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "runtime", "config.yaml");
    const secretsPath = join(root, "secrets.json");
    const cacheRoot = join(root, "cache");
    const runtimeRoot = join(root, "data");
    mkdirSync(join(root, "runtime"), { recursive: true });
    mkdirSync(cacheRoot, { recursive: true });
    writeFileSync(
      src,
      `x-model-sources:
  - id: cline-pass
    models-dev-provider: cline-pass
    credential-pool: cline-pass
    prefix: cline-pass
    base-url: https://api.cline.test/api/v1
    models-url: https://api.cline.test/api/v1/ai/cline/recommended-models
    models-field: clinePass
`,
    );
    writeFileSync(
      secretsPath,
      `${JSON.stringify({
        CLIPROXY_CREDENTIAL_POOLS: {
          "cline-pass": [{ apiKey: "subscription-key", weight: 1 }],
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
          "cline-pass": {
            npm: "@ai-sdk/openai-compatible",
            models: {
              "cline-pass/glm-next": metadata("GLM Next"),
            },
          },
        });
      }
      if (url === "https://api.cline.test/api/v1/ai/cline/recommended-models") {
        return Response.json({
          clinePass: [{ id: "cline-pass/glm-next" }],
          recommended: [{ id: "paid/frontier-next" }],
        });
      }
      if (url === "https://gateway.example.test:9443/v1/models") {
        return Response.json({ data: [] });
      }
      if (url === "https://gateway.example.test:9443/v1/models?client_version=0.144.1") {
        return Response.json({ models: [] });
      }
      return new Response(null, { status: 404 });
    };

    await syncCliProxyConfig(src, dst, secretsPath, DEPLOYMENT, {
      cacheRoot,
      runtimeRoot,
      forceModelRefresh: true,
      fetch: fetchImpl,
      now: () => 1000,
    });

    expect(calls).toEqual([
      "https://models.dev/api.json",
      "https://api.cline.test/api/v1/ai/cline/recommended-models",
      "https://gateway.example.test:9443/v1/models",
      "https://gateway.example.test:9443/v1/models?client_version=0.144.1",
    ]);
    const config = Bun.YAML.parse(readFileSync(dst, "utf8")) as Record<string, any>;
    expect(config["openai-compatibility"]).toMatchObject([
      {
        name: "cline-pass",
        prefix: "cline-pass",
        "base-url": "https://api.cline.test/api/v1",
        models: [{ name: "cline-pass/glm-next", alias: "glm-next" }],
      },
    ]);
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
