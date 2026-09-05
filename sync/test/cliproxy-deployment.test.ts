import { afterEach, beforeEach, type Mock, spyOn, test } from "bun:test";
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
  appendPreservedSections,
  CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
  cliProxyModelsUrl,
  extractPreservedTopLevels,
  isCliProxyTargetReady,
  parseCliProxyDeployment,
  publishCliProxyEndpointTemplates,
  renderCliProxyEndpointTemplate,
  syncCliProxyEndpointTemplate,
} from "@core/cliproxy-deployment.ts";
import { SyncEnv } from "@core/harness.ts";
import { buildSyncPlan, type Job } from "@core/plan.ts";

const REPOSITORY_ROOT = resolve(import.meta.dir, "../..");
const DEPLOYMENT = {
  server: { hostname: hostname() },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
} as const;
const fetchReady = async () => Response.json({ data: [{ id: "ready" }] });

let errorSpy: Mock<(...args: unknown[]) => void>;
beforeEach(() => {
  errorSpy = spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => errorSpy.mockRestore());

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
test("cliproxy_endpoint_replacement_preserves_owned_tables_without_stale_managed_tails", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-endpoint-interleaved-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    mkdirSync(join(root, "generated"), { recursive: true });

    writeFileSync(
      src,
      `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n\n[general]\nmode = "new_fast"\n\n[model]\nname = "gpt-5.6-luna"\n`,
    );
    writeFileSync(
      dst,
      'base_url = "https://old.gateway.test:9443/v1"\n\n[general]\nmode = "old_fast"\nlegacy_flag = true\n\n[hooks.state."orchestrator"]\nspawn_count = 3\n\n[model]\nname = "old-model-name"\ntemperature = 0.2\n\n[projects."~/work/example"]\nmodel = "gpt-5.6-sol"\n',
    );
    chmodSync(dst, 0o600);

    const targets = [{ src, dst, preserveTopLevels: ["hooks.state", "projects"] }];
    assert.equal(
      await publishCliProxyEndpointTemplates(targets, DEPLOYMENT, {
        fetch: fetchReady,
      }),
      "published",
    );

    const expected =
      'base_url = "https://gateway.example.test:9443/v1"\n\n[general]\nmode = "new_fast"\n\n[model]\nname = "gpt-5.6-luna"\n\n[hooks.state."orchestrator"]\nspawn_count = 3\n\n[projects."~/work/example"]\nmodel = "gpt-5.6-sol"\n';
    assert.equal(readFileSync(dst, "utf8"), expected);
    assert.equal(lstatSync(dst).mode & 0o777, 0o600);
    const first = lstatSync(dst);

    await publishCliProxyEndpointTemplates(targets, DEPLOYMENT, {
      fetch: fetchReady,
    });
    assert.equal(readFileSync(dst, "utf8"), expected);
    assert.equal(lstatSync(dst).ino, first.ino);
    assert.equal(lstatSync(dst).mtimeMs, first.mtimeMs);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("extractPreservedTopLevels_extracts_only_matching_subtables_and_array_tables", () => {
  const toml = `
# top-level comments
base_url = "http://localhost:8080"

[general]
mode = "fast"

[hooks.state."orchestrator"]
spawn_count = 3
last_id = "abc\\"def"

[hooks.state.sub]
nested = true

[hooks.statement]
unrelated = true

[[projects.items]]
name = "p1"

[[projects.items]]
name = "p2"

[project]
other = 1

[model]
name = "gpt"
`;

  assert.equal(extractPreservedTopLevels(toml, []), "");
  assert.equal(extractPreservedTopLevels(toml, ["nonexistent"]), "");

  const preserved = extractPreservedTopLevels(toml, ["hooks.state", "projects"]);
  const expected =
    '[hooks.state."orchestrator"]\nspawn_count = 3\nlast_id = "abc\\"def"\n\n[hooks.state.sub]\nnested = true\n\n[[projects.items]]\nname = "p1"\n\n[[projects.items]]\nname = "p2"\n';
  assert.equal(preserved, expected);
});

test("appendPreservedSections_handles_various_newline_layouts", () => {
  assert.equal(
    appendPreservedSections("rendered\n\n", "[table]\nk = 1\n"),
    "rendered\n\n[table]\nk = 1\n",
  );
  assert.equal(
    appendPreservedSections("rendered\n", "[table]\nk = 1\n"),
    "rendered\n\n[table]\nk = 1\n",
  );
  assert.equal(
    appendPreservedSections("rendered", "[table]\nk = 1\n"),
    "rendered\n\n[table]\nk = 1\n",
  );
  assert.equal(appendPreservedSections("rendered\n", ""), "rendered\n");
  assert.equal(appendPreservedSections("", "[table]\nk = 1\n"), "[table]\nk = 1\n");
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

    const proc = Bun.spawnSync(
      [
        process.execPath,
        "-e",
        `import assert from "node:assert/strict";
import { runJobsWithPreserve } from "@core/jobs.ts";

const requests = [];
globalThis.fetch = (async (input, init) => {
  requests.push({ url: String(input), auth: new Headers(init?.headers).get("authorization") });
  return Response.json({ data: [{ id: "ready" }] });
});

const jobs = ${JSON.stringify(jobs)};
const ok = await runJobsWithPreserve(jobs);
assert.equal(ok, true);
const readinessRequest = requests.find((request) => request.url === ${JSON.stringify(modelsUrl)});
assert.equal(readinessRequest?.auth, null);`,
      ],
      {
        cwd: resolve(import.meta.dir, ".."),
        env: Bun.env,
      },
    );

    assert.equal(proc.exitCode, 0);
    assert.equal(readFileSync(dst, "utf8"), `base_url = "${DEPLOYMENT.client.baseUrl}"\n`);
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

    const proc = Bun.spawnSync(
      [
        process.execPath,
        "-e",
        `import assert from "node:assert/strict";
import { runJobsWithPreserve } from "@core/jobs.ts";

globalThis.fetch = (async () => new Response(null, { status: 503 }));

const jobs = ${JSON.stringify(jobs)};
const ok = await runJobsWithPreserve(jobs);
assert.equal(ok, true);`,
      ],
      {
        cwd: resolve(import.meta.dir, ".."),
        env: Bun.env,
      },
    );

    assert.equal(proc.exitCode, 0);
    assert.equal(readFileSync(dst, "utf8"), 'base_url = "old"\n');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
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
    assert.equal(endpointJob.targets.length, 3);
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

test("cliproxy_opencode_endpoint_removes_placeholder_and_injects_baseUrl", () => {
  const home = mkdtempSync(join(tmpdir(), "cliproxy-opencode-test-"));
  try {
    const dstDir = join(home, ".config", "opencode");
    mkdirSync(dstDir, { recursive: true });
    const jsoncSrc = join(home, "opencode.jsonc.tmpl");
    const tsSrc = join(home, "cliproxy.ts.tmpl");
    writeFileSync(jsoncSrc, `const x = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}";\n`);
    writeFileSync(tsSrc, `const x = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}";\n`);

    syncCliProxyEndpointTemplate(jsoncSrc, join(dstDir, "opencode.jsonc"), DEPLOYMENT);
    syncCliProxyEndpointTemplate(tsSrc, join(dstDir, "plugins", "cliproxy.ts"), DEPLOYMENT);

    assert.equal(
      readFileSync(join(dstDir, "opencode.jsonc"), "utf8"),
      `const x = "${DEPLOYMENT.client.baseUrl}";\n`,
    );
    assert.equal(
      readFileSync(join(dstDir, "plugins", "cliproxy.ts"), "utf8"),
      `const x = "${DEPLOYMENT.client.baseUrl}";\n`,
    );
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
