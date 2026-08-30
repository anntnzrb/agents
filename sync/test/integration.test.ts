import { setDefaultTimeout, test } from "bun:test";
import assert from "node:assert/strict";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER } from "@core/cliproxy-deployment.ts";

const SYNC_ROOT = resolve(import.meta.dir, "..");
const TS_SYNC = resolve(SYNC_ROOT, "src/cli.ts");

setDefaultTimeout(30_000);

type RunResult = {
  exitCode: number;
  stdout: string;
  stderr: string;
};

type SnapshotEntry = {
  path: string;
  kind: "file" | "dir" | "symlink";
  content?: string;
};

test("integration_happy_path_matches_expected_outputs", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
    assert.equal(existsSync(join(home, ".codex", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".dsh", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".dsh", "cordis.patch.yml")), true);
    assert.equal(existsSync(join(home, ".dsh", "skills", "skill.txt")), true);
    assert.equal(existsSync(join(home, ".config", "opencode", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".pi", "agent", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "config.yml")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "skills", "legacy")), false);
    assert.equal(existsSync(join(home, ".mcporter", "mcporter.json")), true);
    assert.equal(existsSync(join(home, ".summarize", "config.json")), true);
    const cliProxyConfig = Bun.YAML.parse(
      readFileSync(join(home, ".cli-proxy-api", "config.yaml"), "utf8"),
    ) as Record<string, any>;
    assert.equal(cliProxyConfig["host"], "100.64.0.42");
    assert.equal(cliProxyConfig["port"], 8317);
    assert.equal(cliProxyConfig["remote-management"]["secret-key"], "tailnet");
    assert.equal("api-keys" in cliProxyConfig, false);
    assert.equal(cliProxyConfig["codex-api-key"][0]["api-key"], "upstream-secret");
    assert.equal(cliProxyConfig["codex-api-key"][0]["x-credential-pool"], undefined);
    assert.equal(lstatSync(join(home, ".cli-proxy-api", "config.yaml")).mode & 0o777, 0o600);
    for (const path of [
      join(home, ".codex", "config.toml"),
      join(home, ".config", "opencode", "opencode.jsonc"),
      join(home, ".pi", "agent", "extensions", "cliproxy", "index.ts"),
      join(home, ".omp", "agent", "models.yml"),
    ]) {
      const content = readFileSync(path, "utf8");
      assert.equal(content.includes("http://old-gateway.example.test/v1"), true, path);
      assert.equal(content.includes("CLIPROXY_CLIENT_BASE_URL"), false, path);
    }
    assert.equal(existsSync(join(home, ".pi", "agent", "auth.json")), true);
    for (const command of ["codex", "dsh", "opencode", "pi", "omp"]) {
      const wrapper = join(home, ".local", "bin", command);
      assert.equal(
        readFileSync(wrapper, "utf8").includes("bun x '@anntnzrb/agentium@latest'"),
        true,
      );
    }
  });
});

test("integration_missing_sources_remain_non_fatal", () => {
  withTempDir((root) => {
    const home = join(root, "ts-home");
    mkdirSync(join(home, ".config", "agents"), { recursive: true });
    writeDeployment(home);
    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
  });
});

test("integration_unavailable_client_preserves_all_cliproxy_artifacts", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    writeDeployment(home, "different-host", "http://127.0.0.1:1/v1");

    const configPath = join(home, ".cli-proxy-api", "config.yaml");
    const catalogPath = join(home, ".local", "share", "agentium", "model-catalog", "catalog.json");
    mkdirSync(join(home, ".cli-proxy-api"), { recursive: true });
    mkdirSync(join(home, ".local", "share", "agentium", "model-catalog"), { recursive: true });
    writeFileSync(configPath, "existing-server-config\n", { mode: 0o600 });
    writeFileSync(catalogPath, '{"models":[{"id":"existing"}]}\n', { mode: 0o600 });

    const endpointPaths = [
      join(home, ".codex", "config.toml"),
      join(home, ".config", "opencode", "opencode.jsonc"),
      join(home, ".pi", "agent", "extensions", "cliproxy", "index.ts"),
      join(home, ".omp", "agent", "models.yml"),
    ];
    const activePaths = [configPath, catalogPath, ...endpointPaths];
    const before = activePaths.map((path) => ({
      content: readFileSync(path, "utf8"),
      mode: lstatSync(path).mode & 0o777,
    }));

    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
    assert.deepEqual(
      activePaths.map((path) => ({
        content: readFileSync(path, "utf8"),
        mode: lstatSync(path).mode & 0o777,
      })),
      before,
    );
  });
});

test("integration_package_bootstrap_patches_settings_and_cache_paths", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const sourceRepo = join(root, "repos", "source-pkg");
    const buildRepo = join(root, "repos", "build-pkg");
    setupPackageRepos(sourceRepo, buildRepo);
    writeFileSync(
      join(home, ".config", "agents", "harnesses", "pi", "agent", "packages.json"),
      `${JSON.stringify({ packages: [sourceRepo, buildRepo] }, null, 2)}\n`,
    );

    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
    const settings = readFileSync(join(home, ".pi", "agent", "settings.json"), "utf8");
    assert.equal(settings.includes("source-pkg"), true);
    assert.equal(settings.includes("build-pkg"), true);
    const cacheSnapshot = snapshotSelected(
      join(home, ".local", "share", "agentium", "pi-packages"),
    );
    assert.equal(
      cacheSnapshot.some((entry) => entry.path.includes("source-pkg")),
      true,
    );
    assert.equal(
      cacheSnapshot.some((entry) => entry.path.includes("build-pkg")),
      true,
    );
  });
});

test("integration_invalid_package_json_fails_package_bootstrap", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const badRepo = join(root, "repos", "bad-pkg");
    mkdirSync(badRepo, { recursive: true });
    writeFileSync(join(badRepo, "package.json"), "{not valid json");
    initGitRepo(badRepo);

    writeFileSync(
      join(home, ".config", "agents", "harnesses", "pi", "agent", "packages.json"),
      `${JSON.stringify({ packages: [badRepo] }, null, 2)}\n`,
    );

    const result = runSyncProcess(home);

    assert.notEqual(result.exitCode, 0);
    assert.equal(result.stderr.includes("package bootstrap failed for"), true);
  });
});

test("integration_repeated_runs_remain_idempotent", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const first = runSyncProcess(home);
    const endpointAfterFirst = lstatSync(join(home, ".codex", "config.toml"));
    const snapshotAfterFirst = snapshotHome(home);
    const second = runSyncProcess(home);
    const endpointAfterSecond = lstatSync(join(home, ".codex", "config.toml"));
    const snapshotAfterSecond = snapshotHome(home);

    assert.equal(first.exitCode, 0, first.stderr || first.stdout);
    assert.equal(second.exitCode, 0, second.stderr || second.stdout);
    assert.equal(endpointAfterSecond.ino, endpointAfterFirst.ino);
    assert.equal(endpointAfterSecond.mtimeMs, endpointAfterFirst.mtimeMs);
    assert.deepEqual(snapshotAfterFirst, snapshotAfterSecond);
  });
});

function withTempDir<T>(fn: (root: string) => T): T {
  const root = mkdtempSync(join(tmpdir(), "agents-integration-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function makeFixture(root: string): string {
  const home = join(root, "ts-home");
  mkdirSync(join(home, ".config", "agents"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "harnesses", "codex"), {
    recursive: true,
  });
  mkdirSync(join(home, ".config", "agents", "harnesses", "deepseek"), {
    recursive: true,
  });
  mkdirSync(join(home, ".config", "agents", "harnesses", "opencode"), {
    recursive: true,
  });
  mkdirSync(join(home, ".config", "agents", "harnesses", "omp", "agent"), {
    recursive: true,
  });
  mkdirSync(join(home, ".config", "agents", "harnesses", "pi", "agent"), {
    recursive: true,
  });
  mkdirSync(join(home, ".pi", "agent"), { recursive: true });
  mkdirSync(join(home, ".omp", "agent"), { recursive: true });
  mkdirSync(join(home, ".omp", "agent", "logs"), { recursive: true });
  mkdirSync(join(home, ".codex"), { recursive: true });
  mkdirSync(join(home, ".config", "opencode"), { recursive: true });
  mkdirSync(join(home, ".mcporter"), { recursive: true });
  mkdirSync(join(home, ".summarize"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "sync", "src"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "mcporter"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "summarize"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "cliproxyapi"), { recursive: true });

  writeFixtureFiles(home);
  return home;
}

function writeFixtureFiles(home: string): void {
  writeDeployment(home);
  writeFileSync(join(home, ".config", "agents", "sync", "src", "cli.ts"), "export {};\n");
  writeFileSync(join(home, ".config", "agents", "sync", "tsconfig.json"), "{}\n");
  writeFileSync(join(home, ".config", "agents", "HARNESS.md"), "agent-instructions");
  writeFileSync(join(home, ".config", "agents", "tools", "mcporter", "mcporter.jsonc"), '{"x":1}');
  writeFileSync(join(home, ".config", "agents", "tools", "summarize", "config.json"), '{"x":1}');
  writeFileSync(
    join(home, ".config", "agents", "tools", "cliproxyapi", "config.yaml.tmpl"),
    `host: \${CLIPROXY_LISTEN_HOST}
port: \${CLIPROXY_LISTEN_PORT}
remote-management:
  allow-remote: true
  secret-key: tailnet
codex-api-key:
  - x-credential-pool: fixture
    prefix: fixture
`,
  );
  writeFileSync(
    join(home, ".config", "agents", "tools", "cliproxyapi", "panel.html"),
    "<!doctype html><html><body>management panel</body></html>\n",
  );
  writeFileSync(
    join(home, ".config", "agents", "secrets.local.json"),
    `${JSON.stringify({
      CLIPROXY_CREDENTIAL_POOLS: {
        fixture: [{ apiKey: "upstream-secret", weight: 1 }],
      },
    })}\n`,
  );
  mkdirSync(join(home, ".config", "agents", "skills", "current"), {
    recursive: true,
  });
  writeFileSync(join(home, ".config", "agents", "skills", "current", "skill.txt"), "skill-content");
  mkdirSync(join(home, ".config", "agents", "skills", "legacy"), {
    recursive: true,
  });
  writeFileSync(join(home, ".config", "agents", "skills", "legacy", "old.txt"), "legacy-content");
  writeFileSync(
    join(home, ".config", "agents", "harnesses", "codex", "config.toml"),
    `base_url = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`,
  );
  writeFileSync(
    join(home, ".config", "agents", "harnesses", "opencode", "opencode.jsonc"),
    `"baseURL": "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n`,
  );
  mkdirSync(join(home, ".config", "agents", "harnesses", "pi", "agent", "extensions", "cliproxy"), {
    recursive: true,
  });
  writeFileSync(
    join(
      home,
      ".config",
      "agents",
      "harnesses",
      "pi",
      "agent",
      "extensions",
      "cliproxy",
      "index.ts",
    ),
    `const baseUrl = "${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}";\n`,
  );
  writeFileSync(
    join(home, ".codex", "config.toml"),
    'base_url = "http://old-gateway.example.test/v1"\n',
  );
  writeFileSync(
    join(home, ".config", "opencode", "opencode.jsonc"),
    '"baseURL": "http://old-gateway.example.test/v1"\n',
  );
  mkdirSync(join(home, ".pi", "agent", "extensions", "cliproxy"), { recursive: true });
  writeFileSync(
    join(home, ".pi", "agent", "extensions", "cliproxy", "index.ts"),
    'const baseUrl = "http://old-gateway.example.test/v1";\n',
  );
  writeFileSync(
    join(home, ".config", "agents", "harnesses", "deepseek", "cordis.patch.yml"),
    "[]\n",
  );
  writeFileSync(
    join(home, ".config", "agents", "harnesses", "omp", "agent", "config.yml"),
    "theme:\n  dark: graphite\n",
  );
  writeFileSync(
    join(home, ".config", "agents", "harnesses", "omp", "agent", "models.yml"),
    `baseUrl: ${CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}\n`,
  );
  writeFileSync(
    join(home, ".omp", "agent", "models.yml"),
    "baseUrl: http://old-gateway.example.test/v1\n",
  );
  writeFileSync(join(home, ".pi", "agent", "auth.json"), '{"token":1}');
  writeFileSync(join(home, ".pi", "agent", "settings.json"), "{}\n");
  writeFileSync(join(home, ".omp", "agent", "logs", "keep.txt"), "keep-me");
}

function writeDeployment(
  home: string,
  serverHostname = hostname(),
  clientBaseUrl = "http://127.0.0.1:1/v1",
): void {
  mkdirSync(join(home, ".config", "agents", "tools", "cliproxyapi"), {
    recursive: true,
  });
  writeFileSync(
    join(home, ".config", "agents", "tools", "cliproxyapi", "deployment.json"),
    `${JSON.stringify({
      server: { hostname: serverHostname },
      listen: { host: "100.64.0.42", port: 8317 },
      client: { baseUrl: clientBaseUrl },
    })}\n`,
  );
}

function setupPackageRepos(sourceRepo: string, buildRepo: string): void {
  mkdirSync(join(sourceRepo, "src"), { recursive: true });
  mkdirSync(join(buildRepo, "src"), { recursive: true });
  writeFileSync(
    join(sourceRepo, "package.json"),
    `{
  "pi": {
    "extensions": ["./src/index.ts"]
  }
}
`,
  );
  writeFileSync(join(sourceRepo, "src", "index.ts"), "export default {}\n");
  writeFileSync(
    join(buildRepo, "package.json"),
    `{
  "scripts": {
    "build": "bun run build.ts"
  },
  "pi": {
    "extensions": ["./dist/index.js"]
  }
}
`,
  );
  writeFileSync(
    join(buildRepo, "build.ts"),
    `import { mkdirSync, writeFileSync } from "node:fs";
mkdirSync("dist", { recursive: true });
writeFileSync("dist/index.js", "export default {}\\n");
`,
  );
  initGitRepo(sourceRepo);
  initGitRepo(buildRepo);
}

function initGitRepo(repoPath: string): void {
  const commands = [
    ["git", "init"],
    ["git", "config", "user.name", "Test User"],
    ["git", "config", "user.email", "test@example.com"],
    ["git", "add", "."],
    ["git", "commit", "-m", "init"],
  ];
  for (const command of commands) {
    const result = Bun.spawnSync(command, {
      cwd: repoPath,
      stdout: "pipe",
      stderr: "pipe",
    });
    assert.equal(result.exitCode, 0, result.stderr.toString() || result.stdout.toString());
  }
}

function runSyncProcess(home: string): RunResult {
  const result = Bun.spawnSync(["bun", TS_SYNC], {
    cwd: SYNC_ROOT,
    env: {
      ...Bun.env,
      HOME: home,
      PATH: Bun.env["PATH"] ?? "",
    },
    stdout: "pipe",
    stderr: "pipe",
  });

  return {
    exitCode: result.exitCode,
    stdout: result.stdout.toString(),
    stderr: result.stderr.toString(),
  };
}

function snapshotHome(home: string): SnapshotEntry[] {
  const roots = [
    ".codex",
    ".dsh",
    ".config/opencode",
    ".pi",
    ".omp",
    ".mcporter",
    ".summarize",
    ".cli-proxy-api",
    ".local/share/agentium/sync-managed",
    ".local/share/agentium/pi-packages",
    ".local/bin",
  ];
  const entries: SnapshotEntry[] = [];
  for (const root of roots) {
    const absolute = join(home, root);
    if (existsSync(absolute)) {
      walk(absolute, root, entries);
    }
  }
  return entries.filter((entry) => !entry.path.includes("/sync.lock"));
}

function snapshotSelected(root: string): SnapshotEntry[] {
  const entries: SnapshotEntry[] = [];
  if (existsSync(root)) {
    walk(root, "", entries);
  }
  return entries.filter(
    (entry) => !entry.path.includes("/.git") && !entry.path.includes("/node_modules"),
  );
}

function walk(absolute: string, relative: string, out: SnapshotEntry[]): void {
  const stat = lstatSync(absolute);
  if (stat.isSymbolicLink()) {
    out.push({ path: normalizePath(relative), kind: "symlink" });
    return;
  }
  if (stat.isDirectory()) {
    out.push({ path: normalizePath(relative), kind: "dir" });
    const children = readdirSync(absolute).toSorted();
    for (const child of children) {
      walk(join(absolute, child), relative ? `${relative}/${child}` : child, out);
    }
    return;
  }
  out.push({
    path: normalizePath(relative),
    kind: "file",
    content: readFileSync(absolute, "utf8"),
  });
}

const normalizePath = (path: string): string => path.split(sep).join("/");
