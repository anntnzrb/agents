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
import { renderCliProxyConfig, syncCliProxyConfig } from "@core/cliproxy-config.ts";
import type { CliProxyDeployment } from "@core/cliproxy-deployment.ts";

const DEPLOYMENT: CliProxyDeployment = {
  server: { hostname: "test-gateway" },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
};

test("cliproxy_render_config_expands_native_and_compatibility_credential_pools", () => {
  const rendered = renderCliProxyConfig(
    `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
remote-management:
  allow-remote: true
  secret-key: test-secret
codex-api-key:
  - x-credential-pool: codex-pool
    prefix: codex-custom
openai-compatibility:
  - name: custom-provider
    prefix: custom
    x-credential-pool: compat-pool
`,
    {
      CLIPROXY_CREDENTIAL_POOLS: {
        "codex-pool": [
          { apiKey: "codex-key-1", weight: 2 },
          { apiKey: "codex-key-2", weight: 3, proxyUrl: "http://proxy.test:8080" },
        ],
        "compat-pool": [{ apiKey: "compat-key-1", weight: 1 }, { apiKey: "compat-key-2" }],
      },
    },
    DEPLOYMENT,
  );

  const parsed = Bun.YAML.parse(rendered) as Record<string, any>;
  expect(parsed["host"]).toBe("100.64.0.42");
  expect(parsed["port"]).toBe(9443);
  expect(parsed["remote-management"]).toEqual({
    "allow-remote": true,
    "secret-key": "test-secret",
  });
  expect(parsed["codex-api-key"]).toEqual([
    { "api-key": "codex-key-1", weight: 2, prefix: "codex-custom" },
    {
      "api-key": "codex-key-2",
      weight: 3,
      "proxy-url": "http://proxy.test:8080",
      prefix: "codex-custom",
    },
  ]);
  expect(parsed["openai-compatibility"]).toEqual([
    {
      name: "custom-provider",
      prefix: "custom",
      "api-key-entries": [{ "api-key": "compat-key-1", weight: 1 }, { "api-key": "compat-key-2" }],
    },
  ]);
});

test("cliproxy_render_config_rejects_unreferenced_credential_pools", () => {
  expect(() =>
    renderCliProxyConfig(
      `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
codex-api-key:
  - x-credential-pool: used-pool
`,
      {
        CLIPROXY_CREDENTIAL_POOLS: {
          "used-pool": [{ apiKey: "k1" }],
          "unused-pool": [{ apiKey: "k2" }],
        },
      },
      DEPLOYMENT,
    ),
  ).toThrow("unreferenced CLIProxyAPI credential pool: unused-pool");
});
test("cliproxy_render_config_rejects_x_model_sources", () => {
  expect(() =>
    renderCliProxyConfig(
      `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
x-model-sources:
  - id: example
`,
      { CLIPROXY_CREDENTIAL_POOLS: {} },
      DEPLOYMENT,
    ),
  ).toThrow("unsupported CLIProxyAPI template field: x-model-sources");
});

test("committed_template_renders_with_example_secrets", () => {
  const template = readFileSync(
    join(import.meta.dir, "../../tools/cliproxyapi/config.yaml.tmpl"),
    "utf8",
  );
  const secrets = JSON.parse(
    readFileSync(join(import.meta.dir, "../../secrets.local.example.json"), "utf8"),
  );
  const rendered = renderCliProxyConfig(template, secrets, DEPLOYMENT);
  const parsed = Bun.YAML.parse(rendered) as Record<string, any>;
  expect(parsed["host"]).toBe("100.64.0.42");
  expect(parsed["port"]).toBe(9443);
});

test("cliproxy_render_config_rejects_missing_credential_pools", () => {
  expect(() =>
    renderCliProxyConfig(
      `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
codex-api-key:
  - x-credential-pool: missing-pool
`,
      {
        CLIPROXY_CREDENTIAL_POOLS: {
          "other-pool": [{ apiKey: "k1" }],
        },
      },
      DEPLOYMENT,
    ),
  ).toThrow("missing CLIProxyAPI credential pool: missing-pool");
});

test("cliproxy_sync_writes_private_config_file", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-sync-test-"));
  try {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "runtime", "config.yaml");
    const secretsPath = join(root, "secrets.json");
    mkdirSync(join(root, "runtime"), { recursive: true });

    writeFileSync(
      src,
      `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
remote-management:
  allow-remote: true
codex-api-key:
  - x-credential-pool: fixture
`,
    );
    writeFileSync(
      secretsPath,
      `${JSON.stringify({
        CLIPROXY_CREDENTIAL_POOLS: { fixture: [{ apiKey: "upstream" }] },
      })}\n`,
    );

    await syncCliProxyConfig(src, dst, secretsPath, DEPLOYMENT);

    expect(existsSync(dst)).toBe(true);
    expect(lstatSync(dst).mode & 0o777).toBe(0o600);
    const parsed = Bun.YAML.parse(readFileSync(dst, "utf8")) as Record<string, any>;
    expect(parsed["host"]).toBe("100.64.0.42");
    expect(parsed["port"]).toBe(9443);
    expect(parsed["codex-api-key"]).toEqual([{ "api-key": "upstream" }]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
