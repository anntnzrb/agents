import { test } from "bun:test";
import assert from "node:assert/strict";
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
  CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
  cliProxyModelsUrl,
  isCliProxyTargetReady,
  parseCliProxyDeployment,
  publishCliProxyEndpointTemplates,
  readCliProxyDeployment,
  renderCliProxyEndpointTemplate,
  syncCliProxyEndpointTemplate,
} from "@core/cliproxy-deployment.ts";
import { SyncEnv } from "@core/harness.ts";
import { runJobsWithPreserve } from "@core/jobs.ts";
import { buildSyncPlan, type Job } from "@core/plan.ts";

const REPOSITORY_ROOT = resolve(import.meta.dir, "../..");
const DEPLOYMENT = {
  server: { hostname: hostname() },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
} as const;
const fetchReady = async () => Response.json({ data: [{ id: "ready" }] });

test("cliproxy_deployment_parses_and_normalizes_the_endpoint_boundary", () => {
  assert.deepEqual(
    parseCliProxyDeployment({
      server: { hostname: hostname() },
      listen: { host: "100.64.0.42", port: 9443 },
      client: { baseUrl: "https://gateway.example.test:9443/v1/" },
    }),
    DEPLOYMENT,
  );
  for (const host of [
    "0.0.0.0",
    "000.000.000.000",
    "0.0.0",
    "0",
    "0x0",
    "0000000000",
    "::",
    "::0",
    "0::",
    "0:0:0:0:0:0:0:0",
    "0:0::0",
  ]) {
    assert.throws(
      () =>
        parseCliProxyDeployment({
          server: { hostname: "test-gateway" },
          listen: { host, port: 9443 },
          client: { baseUrl: "https://gateway.example.test:9443/v1" },
        }),
      /specific host or interface address/,
      host,
    );
  }
  assert.throws(
    () =>
      parseCliProxyDeployment({
        server: { hostname: "test-gateway" },
        listen: { host: "100.64.0.42", port: 9443 },
        client: { baseUrl: "https://gateway.example.test:9443/api" },
      }),
    /HTTP\(S\) \/v1 endpoint/,
  );
  assert.throws(
    () =>
      parseCliProxyDeployment({
        server: { hostname: "test-gateway" },
        listen: { host: "100.64.0.42", port: 9443 },
        client: { baseUrl: " https://gateway.example.test:9443/v1" },
      }),
    /HTTP\(S\) \/v1 endpoint/,
  );
  for (const baseUrl of [
    "https://gateway.example.test:9443/v1?migrate=true",
    "https://gateway.example.test:9443/v1#fragment",
  ]) {
    assert.throws(
      () =>
        parseCliProxyDeployment({
          server: { hostname: "test-gateway" },
          listen: { host: "100.64.0.42", port: 9443 },
          client: { baseUrl },
        }),
      /HTTP\(S\) \/v1 endpoint/,
      baseUrl,
    );
  }
  assert.throws(
    () =>
      parseCliProxyDeployment({
        server: { hostname: "test-gateway" },
        listen: { host: "100.64.0.42", port: 9443, typo: true },
        client: { baseUrl: "https://gateway.example.test:9443/v1" },
      }),
    /unknown field typo/,
  );
});

test("cliproxy_endpoint_template_renders_idempotently", () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-endpoint-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    writeFileSync(src, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    chmodSync(src, 0o640);

    syncCliProxyEndpointTemplate(src, dst, DEPLOYMENT);
    assert.equal(readFileSync(dst, "utf8"), `base_url = "${DEPLOYMENT.client.baseUrl}"\n`);
    assert.equal(lstatSync(dst).mode & 0o777, 0o640);
    const first = lstatSync(dst);

    syncCliProxyEndpointTemplate(src, dst, DEPLOYMENT);
    assert.equal(lstatSync(dst).ino, first.ino);
    assert.throws(
      () => renderCliProxyEndpointTemplate("base_url = local\n", DEPLOYMENT),
      /missing CLIProxyAPI endpoint placeholder/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_target_readiness_requires_a_nonempty_models_payload", async () => {
  const responses = [
    [new Response(null, { status: 204 }), false],
    [Response.json({ status: "ok" }), false],
    [Response.json({ data: [] }), false],
    [Response.json({ data: [{ id: "ready" }] }), true],
  ] as const;
  for (const [response, expected] of responses) {
    assert.equal(
      await isCliProxyTargetReady(DEPLOYMENT, {
        fetch: async () => response,
      }),
      expected,
    );
  }
});

test("cliproxy_endpoint_publication_requires_a_keyless_ready_target", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-endpoint-ready-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    writeFileSync(src, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });
    writeFileSync(dst, 'base_url = "old"\n');
    chmodSync(dst, 0o600);

    let requestInit: RequestInit | undefined;
    const skipped = await publishCliProxyEndpointTemplates([{ src, dst }], DEPLOYMENT, {
      fetch: async (_input, init) => {
        requestInit = init;
        return new Response(null, { status: 503 });
      },
    });
    assert.equal(skipped, "skipped");
    assert.equal(readFileSync(dst, "utf8"), 'base_url = "old"\n');
    assert.equal(lstatSync(dst).mode & 0o777, 0o600);
    assert.equal(new Headers(requestInit?.headers).get("authorization"), null);
    assert.equal(requestInit?.cache, "no-store");
    assert.equal(new Headers(requestInit?.headers).get("cache-control"), "no-cache");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_endpoint_publication_rolls_back_all_targets_after_a_write_failure", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-endpoint-transaction-test-"));
  try {
    const srcOne = join(root, "source-one.toml");
    const srcTwo = join(root, "source-two.toml");
    const dstOne = join(root, "generated", "one.toml");
    const dstTwo = join(root, "generated", "two.toml");
    writeFileSync(srcOne, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    writeFileSync(srcTwo, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });
    writeFileSync(dstOne, "old\n");
    chmodSync(dstOne, 0o600);
    mkdirSync(dstTwo, { recursive: true });

    await assert.rejects(
      publishCliProxyEndpointTemplates(
        [
          { src: srcOne, dst: dstOne },
          { src: srcTwo, dst: dstTwo },
        ],
        DEPLOYMENT,
        { fetch: async () => Response.json({ data: [{ id: "ready" }] }) },
      ),
      /EISDIR|directory|not a file/,
    );
    assert.equal(readFileSync(dstOne, "utf8"), "old\n");
    assert.equal(lstatSync(dstOne).mode & 0o777, 0o600);
    assert.equal(lstatSync(dstTwo).isDirectory(), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_endpoint_replacement_preserves_codex_owned_tail", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-endpoint-tail-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    writeFileSync(src, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });

    const ownedTail = `\n[hooks.state."orchestrator"]\nspawn_count = 3\n\n[projects."~/work/example"]\nmodel = "gpt-5.6-sol"\n`;
    const rendered = renderCliProxyEndpointTemplate(readFileSync(src, "utf8"), DEPLOYMENT);
    writeFileSync(dst, `${rendered}${ownedTail}`);
    chmodSync(dst, 0o600);

    const targets = [{ src, dst, preserveTopLevels: ["hooks.state", "projects"] }];
    assert.equal(
      await publishCliProxyEndpointTemplates(targets, DEPLOYMENT, {
        fetch: fetchReady,
      }),
      "published",
    );
    assert.equal(readFileSync(dst, "utf8"), `${rendered}${ownedTail}`);
    assert.equal(lstatSync(dst).mode & 0o777, 0o600);
    const first = lstatSync(dst);

    await publishCliProxyEndpointTemplates(targets, DEPLOYMENT, {
      fetch: fetchReady,
    });
    assert.equal(readFileSync(dst, "utf8"), `${rendered}${ownedTail}`);
    assert.equal(lstatSync(dst).ino, first.ino);
    assert.equal(lstatSync(dst).mtimeMs, first.mtimeMs);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_keyless_readiness_publishes_without_client_keys", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-keyless-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    writeFileSync(src, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });
    writeFileSync(dst, 'base_url = "old"\n');

    const modelsUrl = cliProxyModelsUrl(DEPLOYMENT);
    const requests: Array<{ url: string; init: RequestInit | undefined }> = [];
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
      requests.push({ url: String(input), init });
      return Response.json({ data: [{ id: "ready" }] });
    }) as typeof fetch;
    let ok = false;
    try {
      const jobs: Job[] = [
        {
          kind: "CliProxyReadiness",
          deployment: DEPLOYMENT,
          gatewayHost: false,
        },
        {
          kind: "CliProxyEndpointTemplates",
          targets: [{ src, dst }],
          deployment: DEPLOYMENT,
        },
      ];
      ok = await runJobsWithPreserve(jobs);
    } finally {
      globalThis.fetch = originalFetch;
    }

    assert.equal(ok, true);
    assert.equal(readFileSync(dst, "utf8"), `base_url = "${DEPLOYMENT.client.baseUrl}"\n`);
    const readinessRequest = requests.find((request) => request.url === modelsUrl);
    assert.equal(new Headers(readinessRequest?.init?.headers).get("authorization"), null);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_readiness_failure_preserves_endpoints", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-unready-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    writeFileSync(src, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });
    writeFileSync(dst, 'base_url = "old"\n');

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response(null, { status: 503 })) as unknown as typeof fetch;
    try {
      const jobs: Job[] = [
        {
          kind: "CliProxyReadiness",
          deployment: DEPLOYMENT,
          gatewayHost: false,
        },
        {
          kind: "CliProxyEndpointTemplates",
          targets: [{ src, dst }],
          deployment: DEPLOYMENT,
        },
      ];
      assert.equal(await runJobsWithPreserve(jobs), true);
    } finally {
      globalThis.fetch = originalFetch;
    }

    assert.equal(readFileSync(dst, "utf8"), 'base_url = "old"\n');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("cliproxy_deployment_is_the_only_committed_endpoint_value", () => {
  const deployment = readCliProxyDeployment(
    join(REPOSITORY_ROOT, "tools", "cliproxyapi", "deployment.json"),
  );
  const sources = [
    join("harnesses", "codex", "config.toml"),
    join("harnesses", "opencode", "opencode.jsonc"),
    join("harnesses", "pi", "agent", "extensions", "cliproxy", "index.ts"),
    join("harnesses", "omp", "agent", "models.yml"),
  ];
  for (const relativePath of sources) {
    const source = readFileSync(join(REPOSITORY_ROOT, relativePath), "utf8");
    assert.match(source, /\$\{CLIPROXY_CLIENT_BASE_URL\}/, relativePath);
    assert.doesNotMatch(source, new RegExp(escapeRegExp(deployment.client.baseUrl)), relativePath);
    assert.doesNotMatch(source, new RegExp(escapeRegExp(deployment.listen.host)), relativePath);
  }

  const template = readFileSync(
    join(REPOSITORY_ROOT, "tools", "cliproxyapi", "config.yaml.tmpl"),
    "utf8",
  );
  assert.match(template, /host: "\$\{CLIPROXY_LISTEN_HOST\}"/);
  assert.match(template, /port: \$\{CLIPROXY_LISTEN_PORT\}/);
  assert.match(template, /remote-management:\n\s+allow-remote: true/);
  assert.match(template, /secret-key: tailnet/);
  assert.match(template, /usage-statistics-enabled: true/);
  assert.match(template, /ws-auth: false/);
  assert.doesNotMatch(template, /api-keys:/);
  assert.doesNotMatch(template, /base-url: "https:\/\/openrouter\.ai/);
  const config = Bun.YAML.parse(template) as Record<string, any>;
  const commandCode = (config["x-model-sources"] as readonly Record<string, unknown>[]).find(
    (source) => source["id"] === "command-code",
  );
  assert.deepEqual(commandCode, {
    id: "command-code",
    "models-dev-provider": "openrouter",
    "credential-pool": "command-code",
    prefix: "cmd",
    "base-url": "https://api.commandcode.ai/provider/v1",
  });
  assert.doesNotMatch(template, new RegExp(escapeRegExp(deployment.listen.host)));
});

test("cliproxy_committed_source_keeps_sessions_sticky_and_retries_the_full_pool", () => {
  const source = readFileSync(
    join(REPOSITORY_ROOT, "tools", "cliproxyapi", "config.yaml.tmpl"),
    "utf8",
  );
  const config = Bun.YAML.parse(source) as Record<string, any>;

  assert.equal(config["request-retry"], 3);
  assert.equal(config["max-retry-credentials"], 0);
  assert.equal(config["max-retry-interval"], 30);
  assert.equal(config["disable-cooling"], false);
  assert.equal(config["save-cooldown-status"], true);
  assert.deepEqual(config["routing"], {
    strategy: "weighted-round-robin",
    "session-affinity": true,
    "session-affinity-ttl": "1h",
  });
  assert.deepEqual(config["streaming"], { "bootstrap-retries": 1 });
});

test("cliproxy_codex_aliases_preserve_reasoning_and_fast_service_tiers", () => {
  const source = readFileSync(
    join(REPOSITORY_ROOT, "tools", "cliproxyapi", "config.yaml.tmpl"),
    "utf8",
  );
  const config = Bun.YAML.parse(source) as Record<string, any>;
  const aliases = config["oauth-model-alias"]["codex"] as readonly Record<string, any>[];
  const rules = config["payload"]["override"] as readonly Record<string, any>[];
  const codexRules = rules.filter((rule) =>
    rule["models"].some((model: Record<string, unknown>) => model["protocol"] === "codex"),
  );

  assert.deepEqual(
    aliases.filter((alias) =>
      [
        "nnn-gpt-5.6-luna-max",
        "nnn-gpt-5.6-luna-max-fast",
        "nnn-gpt-5.6-terra-max",
        "nnn-gpt-5.6-terra-max-fast",
      ].includes(alias["alias"]),
    ),
    [
      {
        name: "gpt-5.6-luna",
        alias: "nnn-gpt-5.6-luna-max",
        "display-name": "[nnn] GPT-5.6 Luna (Max)",
        fork: true,
        "force-mapping": true,
      },
      {
        name: "gpt-5.6-luna",
        alias: "nnn-gpt-5.6-luna-max-fast",
        "display-name": "[nnn] GPT-5.6 Luna (Max) (Fast)",
        fork: true,
        "force-mapping": true,
      },
      {
        name: "gpt-5.6-terra",
        alias: "nnn-gpt-5.6-terra-max",
        "display-name": "[nnn] GPT-5.6 Terra (Max)",
        fork: true,
        "force-mapping": true,
      },
      {
        name: "gpt-5.6-terra",
        alias: "nnn-gpt-5.6-terra-max-fast",
        "display-name": "[nnn] GPT-5.6 Terra (Max) (Fast)",
        fork: true,
        "force-mapping": true,
      },
    ],
  );
  assert.deepEqual(
    codexRules.filter((rule) =>
      ["gpt-5.6-luna", "gpt-5.6-terra"].includes(rule["models"][0]["name"]),
    ),
    [
      {
        models: [{ name: "gpt-5.6-luna", protocol: "codex" }],
        params: { "reasoning.effort": "max" },
      },
      {
        models: [{ name: "gpt-5.6-terra", protocol: "codex" }],
        params: { "reasoning.effort": "max" },
      },
    ],
  );
  assert.deepEqual(
    codexRules.filter((rule) =>
      ["nnn-gpt-5.6-luna-max-fast", "nnn-gpt-5.6-terra-max-fast"].includes(
        rule["models"][0]["name"],
      ),
    ),
    [
      {
        models: [{ name: "nnn-gpt-5.6-luna-max-fast", protocol: "codex" }],
        params: { service_tier: "fast" },
      },
      {
        models: [{ name: "nnn-gpt-5.6-terra-max-fast", protocol: "codex" }],
        params: { service_tier: "fast" },
      },
    ],
  );
});
test("cliproxy_custom_aliases_use provider-native model and payload shapes", () => {
  const source = readFileSync(
    join(REPOSITORY_ROOT, "tools", "cliproxyapi", "config.yaml.tmpl"),
    "utf8",
  );
  const config = Bun.YAML.parse(source) as Record<string, any>;
  const profiles = config["openai-compatibility"] as readonly Record<string, any>[];
  const cline = profiles.find((profile) => profile["name"] === "cline-pass-custom");
  const commandCode = profiles.find((profile) => profile["name"] === "command-code-custom");
  const rules = config["payload"]["override"] as readonly Record<string, any>[];
  const antigravity = rules.find((rule) =>
    rule["models"].some((model: Record<string, unknown>) => model["protocol"] === "antigravity"),
  );

  assert.deepEqual(
    cline?.["models"].map((model: Record<string, unknown>) => model["name"]),
    [
      "cline-pass/deepseek-v4-flash",
      "cline-pass/deepseek-v4-pro",
      "cline-pass/glm-5.3",
      "cline-pass/kimi-k3",
      "cline-pass/qwen3.8-max",
    ],
  );
  assert.deepEqual(
    commandCode?.["models"].map((model: Record<string, unknown>) => model["name"]),
    [
      "deepseek/deepseek-v4-flash",
      "deepseek/deepseek-v4-pro",
      "zai-org/GLM-5.3",
      "moonshotai/Kimi-K3",
    ],
  );
  assert.deepEqual(antigravity?.["params"], {
    "generationConfig.thinkingConfig.thinkingLevel": "medium",
  });
});

test("cliproxy_endpoint_publication_is_one_job_after_config_and_directory_copies", () => {
  const home = mkdtempSync(join(tmpdir(), "cliproxy-plan-test-"));
  try {
    const agents = join(home, ".config", "agents");
    const tools = join(agents, "tools");
    mkdirSync(join(tools, "cliproxyapi"), { recursive: true });
    writeFileSync(join(tools, "cliproxyapi", "deployment.json"), `${JSON.stringify(DEPLOYMENT)}\n`);
    for (const [harness, relativeRoot, relativeFile] of [
      ["codex", "", "config.toml"],
      ["opencode", "", "opencode.jsonc"],
      ["pi", "agent", join("extensions", "cliproxy", "index.ts")],
      ["omp", "agent", "models.yml"],
    ] as const) {
      const sourceRoot = join(agents, "harnesses", harness, relativeRoot);
      mkdirSync(join(sourceRoot, relativeFile, ".."), { recursive: true });
      writeFileSync(join(sourceRoot, relativeFile), CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER);
    }

    const plan = buildSyncPlan(SyncEnv.fromHome(home, 1000, { platform: "linux" }));
    const endpointJobs = plan.jobs.filter((job) => job.kind === "CliProxyEndpointTemplates");
    assert.equal(endpointJobs.length, 1);
    const endpointJob = endpointJobs[0];
    assert.ok(endpointJob);
    if (endpointJob?.kind !== "CliProxyEndpointTemplates") {
      return;
    }
    assert.equal(endpointJob.targets.length, 4);
    const codexTarget = endpointJob.targets.find((target) =>
      target.dst.endsWith(join(".codex", "config.toml")),
    );
    assert.deepEqual(codexTarget?.preserveTopLevels, ["hooks.state", "projects"]);
    const readinessJob = plan.jobs.find((job) => job.kind === "CliProxyReadiness");
    assert.ok(readinessJob?.kind === "CliProxyReadiness");
    const configJobIndex = plan.jobs.findIndex((job) => job.kind === "CliProxyConfig");
    assert.ok(configJobIndex >= 0);
    assert.ok(plan.jobs.indexOf(endpointJob) > configJobIndex);
    for (const target of endpointJob.targets) {
      const directoryJobIndex = plan.jobs.findIndex(
        (job) => job.kind === "Dir" && target.dst.startsWith(`${job.dst}/`),
      );
      assert.notEqual(directoryJobIndex, -1, target.dst);
      assert.ok(plan.jobs.indexOf(endpointJob) > directoryJobIndex, target.dst);
      const directoryJob = plan.jobs[directoryJobIndex];
      assert.equal(directoryJob?.kind, "Dir");
      if (directoryJob?.kind === "Dir") {
        const relativePath = target.dst.slice(directoryJob.dst.length + 1);
        assert.ok(directoryJob.preservePaths?.includes(relativePath), target.dst);
      }
    }
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
