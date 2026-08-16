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
  isCliProxyTargetReady,
  parseCliProxyDeployment,
  publishCliProxyEndpointTemplates,
  readCliProxyDeployment,
  renderCliProxyEndpointTemplate,
  syncCliProxyEndpointTemplate,
} from "@core/cliproxy-deployment.ts";
import { SyncEnv } from "@core/harness.ts";
import { buildSyncPlan } from "@core/plan.ts";

const REPOSITORY_ROOT = resolve(import.meta.dir, "../..");
const DEPLOYMENT = {
  server: { hostname: hostname() },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
} as const;

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
      await isCliProxyTargetReady(DEPLOYMENT, "client-key", {
        fetch: async () => response,
      }),
      expected,
    );
  }
});

test("cliproxy_endpoint_publication_requires_an_authenticated_uncached_target", async () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-endpoint-ready-test-"));
  try {
    const src = join(root, "source.toml");
    const dst = join(root, "generated", "config.toml");
    const keyPath = join(root, "runtime", "client-api-key");
    writeFileSync(src, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });
    writeFileSync(dst, 'base_url = "old"\n');
    chmodSync(dst, 0o600);
    mkdirSync(join(root, "runtime"), { recursive: true });
    writeFileSync(keyPath, "client-key\n");

    let requestInit: RequestInit | undefined;
    const skipped = await publishCliProxyEndpointTemplates([{ src, dst }], DEPLOYMENT, keyPath, {
      fetch: async (_input, init) => {
        requestInit = init;
        return new Response(null, { status: 503 });
      },
    });
    assert.equal(skipped, "skipped");
    assert.equal(readFileSync(dst, "utf8"), 'base_url = "old"\n');
    assert.equal(lstatSync(dst).mode & 0o777, 0o600);
    assert.equal(new Headers(requestInit?.headers).get("authorization"), "Bearer client-key");
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
    const keyPath = join(root, "runtime", "client-api-key");
    writeFileSync(srcOne, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    writeFileSync(srcTwo, `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`);
    mkdirSync(join(root, "generated"), { recursive: true });
    writeFileSync(dstOne, "old\n");
    chmodSync(dstOne, 0o600);
    mkdirSync(dstTwo, { recursive: true });
    mkdirSync(join(root, "runtime"), { recursive: true });
    writeFileSync(keyPath, "client-key\n");

    await assert.rejects(
      publishCliProxyEndpointTemplates(
        [
          { src: srcOne, dst: dstOne },
          { src: srcTwo, dst: dstTwo },
        ],
        DEPLOYMENT,
        keyPath,
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

test("cliproxy_deployment_is_the_only_committed_endpoint_value", () => {
  const deployment = readCliProxyDeployment(
    join(REPOSITORY_ROOT, "assets", "cliproxyapi.deployment.json"),
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

  const template = readFileSync(join(REPOSITORY_ROOT, "assets", "cliproxyapi.yaml.tmpl"), "utf8");
  assert.match(template, /host: "\$\{CLIPROXY_LISTEN_HOST\}"/);
  assert.match(template, /port: \$\{CLIPROXY_LISTEN_PORT\}/);
  assert.doesNotMatch(template, new RegExp(escapeRegExp(deployment.listen.host)));
});

test("cliproxy_endpoint_publication_is_one_job_after_config_and_directory_copies", () => {
  const home = mkdtempSync(join(tmpdir(), "cliproxy-plan-test-"));
  try {
    const agents = join(home, ".config", "agents");
    const assets = join(agents, "assets");
    mkdirSync(assets, { recursive: true });
    writeFileSync(join(assets, "cliproxyapi.deployment.json"), `${JSON.stringify(DEPLOYMENT)}\n`);
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
