import { setDefaultTimeout, test } from "bun:test";
import assert from "node:assert/strict";
import {
  copyFileSync,
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER } from "@core/cliproxy-deployment.ts";
import { releaseSyncLock, tryAcquireSyncLock } from "@runtime/lock.ts";
import { PRISTINE_PATH, seedRuntimeRelease, sharedToolCacheEnv } from "./support/cache-env.ts";

const SYNC_ROOT = resolve(import.meta.dir, "..");
const TS_SYNC = resolve(SYNC_ROOT, "src/cli.ts");

setDefaultTimeout(30_000);

const OFFLINE_NPM_ENV = {
  npm_config_fetch_retries: "0",
  npm_config_fetch_timeout: "100",
  npm_config_registry: "http://127.0.0.1:1/",
  NPM_CONFIG_FETCH_RETRIES: "0",
  NPM_CONFIG_FETCH_TIMEOUT: "100",
  NPM_CONFIG_REGISTRY: "http://127.0.0.1:1/",
};

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

test("integration_cli_help_flags_exit_0", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    for (const args of [["--help"], ["-h"], ["help"], ["sync", "--help"], ["launch", "--help"]]) {
      const result = await runSyncProcess(home, args);
      assert.equal(result.exitCode, 0, `args ${args.join(" ")} failed: ${result.stderr}`);
      assert.equal(
        result.stdout.includes("sync — Reconcile") || result.stdout.includes("Usage: sync launch"),
        true,
        `expected help output for ${args.join(" ")}, got: ${result.stdout}`,
      );
    }
  });
});

test("integration_cli_syntax_errors_exit_2", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const badCommand = await runSyncProcess(home, ["invalid-subcommand"]);
    assert.equal(badCommand.exitCode, 2);
    assert.equal(badCommand.stderr.includes("sync: usage: sync"), true, badCommand.stderr);

    const badLaunchNoName = await runSyncProcess(home, ["launch"]);
    assert.equal(badLaunchNoName.exitCode, 2);
    assert.equal(
      badLaunchNoName.stderr.includes("sync: usage: launch NAME -- [ARGS...]"),
      true,
      badLaunchNoName.stderr,
    );

    const badLaunchNoSeparator = await runSyncProcess(home, ["launch", "codex", "no-separator"]);
    assert.equal(badLaunchNoSeparator.exitCode, 2);
    assert.equal(
      badLaunchNoSeparator.stderr.includes("sync: usage: launch NAME -- [ARGS...]"),
      true,
      badLaunchNoSeparator.stderr,
    );
  });
});

test("integration_missing_runtime_sources_fails_sync_exit_1", async () => {
  await withTempDir(async (root) => {
    const home = join(root, "ts-home");
    mkdirSync(join(home, ".config", "agents"), { recursive: true });
    writeDeployment(home);
    const result = await runSyncProcess(home);

    assert.equal(result.exitCode, 1, result.stderr || result.stdout);
    assert.equal(result.stderr.includes("missing or unreadable runtime source"), true);
  });
});

test("integration_malformed_config_fails_sync_exit_1", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    writeFileSync(
      join(home, ".config", "agents", "tools", "cliproxyapi", "deployment.json"),
      "{ invalid json syntax\n",
    );

    const result = await runSyncProcess(home);
    assert.equal(result.exitCode, 1, result.stderr || result.stdout);
    assert.equal(
      result.stderr.includes("parse CLIProxyAPI deployment") ||
        result.stderr.includes("deployment.json"),
      true,
      result.stderr,
    );
  });
});

test("integration_happy_path_matches_expected_outputs", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const result = await runSyncProcess(home);

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
    assert.equal(
      existsSync(join(home, ".local", "share", "agents", "cliproxyapi", "client-api-key")),
      false,
    );
    for (const path of [
      join(home, ".codex", "config.toml"),
      join(home, ".config", "opencode", "opencode.jsonc"),
      join(home, ".omp", "agent", "models.yml"),
    ]) {
      const content = readFileSync(path, "utf8");
      assert.equal(content.includes("http://old-gateway.example.test/v1"), true, path);
      assert.equal(content.includes("CLIPROXY_CLIENT_BASE_URL"), false, path);
    }
    const installedCli = join(home, ".local", "share", "agents", "sync-current", "src", "cli.ts");
    assert.equal(existsSync(installedCli), true, installedCli);
    const installedCliContent = readFileSync(installedCli, "utf8");
    assert.equal(installedCliContent.length > 0, true, installedCli);
    assert.equal(existsSync(join(home, ".pi", "agent", "auth.json")), true);
    for (const command of ["codex", "dsh", "opencode", "pi", "omp"]) {
      const wrapper = join(home, ".local", "bin", command);
      const wrapperText = readFileSync(wrapper, "utf8");
      assert.equal(existsSync(wrapper), true, wrapper);
      assert.equal(wrapperText.includes("agents-managed-wrapper:v1"), true);
      assert.equal(wrapperText.includes(".local/share/agents/sync-current"), true);
      assert.equal(wrapperText.includes(SYNC_ROOT), false);
      assert.equal(wrapperText.includes(".config/agents/sync"), false);
    }
  });
});

test("integration_repeated_runs_remain_idempotent", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const first = await runSyncProcess(home);
    const endpointAfterFirst = lstatSync(join(home, ".codex", "config.toml"));
    const snapshotAfterFirst = snapshotHome(home);
    const second = await runSyncProcess(home);
    const endpointAfterSecond = lstatSync(join(home, ".codex", "config.toml"));
    const snapshotAfterSecond = snapshotHome(home);

    assert.equal(first.exitCode, 0, first.stderr || first.stdout);
    assert.equal(second.exitCode, 0, second.stderr || second.stdout);
    assert.equal(endpointAfterSecond.ino, endpointAfterFirst.ino);
    assert.equal(endpointAfterSecond.mtimeMs, endpointAfterFirst.mtimeMs);
    assert.deepEqual(snapshotAfterFirst, snapshotAfterSecond);
  });
});

test("integration_owned_entry_cleanup_and_unmanaged_file_preservation", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);

    // Create an unmanaged log file in ~/.omp/agent/logs/
    const unmanagedLog = join(home, ".omp", "agent", "logs", "custom-user.log");
    writeFileSync(unmanagedLog, "user-log-content\n");

    // Create an unmanaged binary in ~/.local/bin/
    const unmanagedBin = join(home, ".local", "bin", "user-tool");
    mkdirSync(join(home, ".local", "bin"), { recursive: true });
    writeFileSync(unmanagedBin, "#!/bin/sh\necho 'user-tool'\n", { mode: 0o755 });

    // First sync: creates managed skills and wrappers
    const firstResult = await runSyncProcess(home);
    assert.equal(firstResult.exitCode, 0, firstResult.stderr || firstResult.stdout);

    const skillPath = join(home, ".omp", "agent", "skills", "skill.txt");
    assert.equal(existsSync(skillPath), true, skillPath);
    assert.equal(existsSync(unmanagedLog), true, unmanagedLog);
    assert.equal(readFileSync(unmanagedLog, "utf8"), "user-log-content\n");
    assert.equal(existsSync(unmanagedBin), true, unmanagedBin);

    // Remove legacy skill from SSOT to turn it into a stale owned entry
    rmSync(join(home, ".config", "agents", "skills", "legacy"), {
      recursive: true,
      force: true,
    });

    // Second sync: cleans up stale owned skill but preserves unmanaged user files
    const secondResult = await runSyncProcess(home);
    assert.equal(secondResult.exitCode, 0, secondResult.stderr || secondResult.stdout);

    assert.equal(existsSync(skillPath), true, skillPath);
    assert.equal(existsSync(unmanagedLog), true, unmanagedLog);
    assert.equal(readFileSync(unmanagedLog, "utf8"), "user-log-content\n");
    assert.equal(existsSync(unmanagedBin), true, unmanagedBin);

    // Unmanaged wrapper conflict: overwrite ~/.local/bin/codex with an unmanaged script
    const unmanagedCodex = join(home, ".local", "bin", "codex");
    writeFileSync(unmanagedCodex, "#!/bin/sh\necho 'custom-codex'\n", { mode: 0o755 });

    const thirdResult = await runSyncProcess(home);
    assert.equal(thirdResult.exitCode, 0, thirdResult.stderr || thirdResult.stdout);
    assert.equal(
      thirdResult.stderr.includes("preserving unmanaged wrapper conflict"),
      true,
      thirdResult.stderr,
    );
    assert.equal(readFileSync(unmanagedCodex, "utf8"), "#!/bin/sh\necho 'custom-codex'\n");
  });
});

test("integration_failed_publication_clean_recovery", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    writeDeployment(home, "different-host", "http://127.0.0.1:1/v1");

    const endpointPaths = [
      join(home, ".codex", "config.toml"),
      join(home, ".config", "opencode", "opencode.jsonc"),
      join(home, ".omp", "agent", "models.yml"),
    ];
    const originalContents = endpointPaths.map((p) => readFileSync(p, "utf8"));

    const skippedResult = await runSyncProcess(home);
    assert.equal(skippedResult.exitCode, 0, skippedResult.stderr || skippedResult.stdout);
    for (let i = 0; i < endpointPaths.length; i++) {
      assert.equal(readFileSync(endpointPaths[i]!, "utf8"), originalContents[i]);
    }

    writeDeployment(home, hostname(), "http://100.64.0.42:8317/v1");
    const recoveryResult = await runSyncProcess(home);
    assert.equal(recoveryResult.exitCode, 0, recoveryResult.stderr || recoveryResult.stdout);
    for (const path of endpointPaths) {
      const content = readFileSync(path, "utf8");
      assert.equal(content.includes("CLIPROXY_CLIENT_BASE_URL"), false, path);
    }
  });
});

test("integration_process_lock_contention_and_release_on_exit", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const stateDir = join(home, ".local", "share", "agents", "sync-managed");
    const lockPath = join(stateDir, "sync.lock");

    const lock = tryAcquireSyncLock(stateDir, lockPath);
    assert.notEqual(lock, undefined);

    const contendedResult = await runSyncProcess(home);
    assert.equal(contendedResult.exitCode, 0, contendedResult.stderr || contendedResult.stdout);
    assert.equal(
      contendedResult.stderr.includes("another sync is already running; skipping"),
      true,
      contendedResult.stderr,
    );

    releaseSyncLock(lock!);

    const afterReleaseResult = await runSyncProcess(home);
    assert.equal(
      afterReleaseResult.exitCode,
      0,
      afterReleaseResult.stderr || afterReleaseResult.stdout,
    );
    assert.equal(existsSync(join(home, ".codex", "AGENTS.md")), true);
  });
});

test("integration_cached_launch_fallback_when_offline", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const syncResult = await runSyncProcess(home);
    assert.equal(syncResult.exitCode, 0, syncResult.stderr || syncResult.stdout);

    seedCachedNpmPackage(
      home,
      { tool: "codex", package: "@openai/codex", bin: "codex" },
      "0.1.0",
      `#!/bin/sh\necho "mock-codex-0.1.0:mode=cached args=$*"\nexit 0\n`,
    );

    const launchResult = await runSyncProcess(home, ["launch", "codex", "--", "--hello", "world"], {
      env: OFFLINE_NPM_ENV,
    });
    assert.equal(launchResult.exitCode, 0, launchResult.stderr || launchResult.stdout);
    assert.equal(
      launchResult.stderr.includes("using cached codex@0.1.0"),
      true,
      launchResult.stderr,
    );
    assert.equal(
      launchResult.stdout.includes("mock-codex-0.1.0:mode=cached args=--hello world"),
      true,
      launchResult.stdout,
    );
  });
});

test("integration_missing_runtime_wrapper_returns_127_with_hint", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const syncResult = await runSyncProcess(home);
    assert.equal(syncResult.exitCode, 0, syncResult.stderr || syncResult.stdout);

    const wrapper = join(home, ".local", "bin", "codex");
    assert.equal(existsSync(wrapper), true, wrapper);

    const runtimeDir = join(home, ".local", "share", "agents", "sync-current");
    rmSync(runtimeDir, { recursive: true, force: true });

    const result = await runWrapper(wrapper, ["--version"], { home });
    assert.equal(result.exitCode, 127, result.stderr || result.stdout);
    assert.equal(
      result.stderr.includes(
        "agents: sync runtime is missing; run sync from the agents repository",
      ),
      true,
      result.stderr,
    );
  });
});

test("integration_environment_variable_precedence_dot_env_vs_parent", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    writeFileSync(
      join(home, ".config", "agents", ".env"),
      `BASE_FROM_DOTENV=dotenv_val
OVERRIDE_VAR=dotenv_val
`,
    );

    const syncResult = await runSyncProcess(home);
    assert.equal(syncResult.exitCode, 0, syncResult.stderr || syncResult.stdout);

    seedCachedNpmPackage(
      home,
      { tool: "codex", package: "@openai/codex", bin: "codex" },
      "0.1.0",
      `#!/bin/sh
echo "BASE_FROM_DOTENV=$BASE_FROM_DOTENV"
echo "OVERRIDE_VAR=$OVERRIDE_VAR"
echo "PARENT_ONLY_VAR=$PARENT_ONLY_VAR"
exit 0
`,
    );

    const launchResult = await runSyncProcess(home, ["launch", "codex"], {
      env: {
        ...OFFLINE_NPM_ENV,
        OVERRIDE_VAR: "parent_val",
        PARENT_ONLY_VAR: "parent_val",
      },
    });

    assert.equal(launchResult.exitCode, 0, launchResult.stderr || launchResult.stdout);
    assert.equal(
      launchResult.stdout.includes("BASE_FROM_DOTENV=dotenv_val"),
      true,
      launchResult.stdout,
    );
    assert.equal(
      launchResult.stdout.includes("OVERRIDE_VAR=parent_val"),
      true,
      launchResult.stdout,
    );
    assert.equal(
      launchResult.stdout.includes("PARENT_ONLY_VAR=parent_val"),
      true,
      launchResult.stdout,
    );
  });
});

test("integration_unavailable_client_preserves_all_cliproxy_artifacts", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    writeDeployment(home, "different-host", "http://127.0.0.1:1/v1");

    const configPath = join(home, ".cli-proxy-api", "config.yaml");
    mkdirSync(join(home, ".cli-proxy-api"), { recursive: true });
    writeFileSync(configPath, "existing-server-config\n", { mode: 0o600 });

    const endpointPaths = [
      join(home, ".codex", "config.toml"),
      join(home, ".config", "opencode", "opencode.jsonc"),
      join(home, ".omp", "agent", "models.yml"),
    ];
    const activePaths = [configPath, ...endpointPaths];
    const before = activePaths.map((path) => ({
      content: readFileSync(path, "utf8"),
      mode: lstatSync(path).mode & 0o777,
    }));

    const result = await runSyncProcess(home);

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

test("integration_package_bootstrap_patches_settings_and_cache_paths", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const sourceRepo = join(root, "repos", "source-pkg");
    const buildRepo = join(root, "repos", "build-pkg");
    setupPackageRepos(sourceRepo, buildRepo);
    writeFileSync(
      join(home, ".config", "agents", "harnesses", "pi", "agent", "packages.json"),
      `${JSON.stringify({ packages: [sourceRepo, buildRepo] }, null, 2)}\n`,
    );

    const result = await runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
    const settings = readFileSync(join(home, ".pi", "agent", "settings.json"), "utf8");
    assert.equal(settings.includes("source-pkg"), true);
    assert.equal(settings.includes("build-pkg"), true);
    const cacheSnapshot = snapshotSelected(join(home, ".local", "share", "agents", "pi-packages"));
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

test("integration_invalid_package_json_fails_package_bootstrap", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const badRepo = join(root, "repos", "bad-pkg");
    mkdirSync(badRepo, { recursive: true });
    writeFileSync(join(badRepo, "package.json"), "{not valid json");
    initGitRepo(badRepo);

    writeFileSync(
      join(home, ".config", "agents", "harnesses", "pi", "agent", "packages.json"),
      `${JSON.stringify({ packages: [badRepo] }, null, 2)}\n`,
    );

    const result = await runSyncProcess(home);

    assert.notEqual(result.exitCode, 0);
    assert.equal(result.stderr.includes("package bootstrap failed for"), true);
  });
});

const FAKE_RUNTIME = `const args = process.argv.slice(2);
console.log("mode=" + args[0]);
console.log("sourceName=" + args[1]);
console.log("separator=" + args[2]);
for (let i = 3; i < args.length; i++) {
  console.log("arg[" + (i - 3) + "]=" + args[i]);
}
process.exit(42);
`;

test("integration_wrapper_forwards_arguments_to_faked_runtime", async () => {
  await withTempDir(async (root) => {
    const home = makeFixture(root);
    const syncResult = await runSyncProcess(home);
    assert.equal(syncResult.exitCode, 0, syncResult.stderr || syncResult.stdout);

    const wrapper = join(home, ".local", "bin", "codex");
    const installedCli = join(home, ".local", "share", "agents", "sync-current", "src", "cli.ts");
    assert.equal(existsSync(wrapper), true, wrapper);
    assert.equal(existsSync(installedCli), true, installedCli);

    const wrapperText = readFileSync(wrapper, "utf8");
    assert.equal(wrapperText.includes("agents-managed-wrapper:v1"), true);
    assert.equal(wrapperText.includes(".local/share/agents/sync-current"), true);
    assert.equal(wrapperText.includes(SYNC_ROOT), false);
    assert.equal(wrapperText.includes(".config/agents/sync"), false);

    writeFileSync(installedCli, FAKE_RUNTIME);

    const child = Bun.spawn([wrapper, "--sentinel", "one", "two three"], {
      cwd: home,
      stdin: "ignore",
      stdout: "pipe",
      stderr: "pipe",
      killSignal: "SIGKILL",
      env: {
        ...Bun.env,
        HOME: home,
        XDG_CACHE_HOME: join(home, ".cache"),
        PATH: PRISTINE_PATH,
        ...sharedToolCacheEnv,
      },
    });

    const timeout = setTimeout(() => {
      try {
        child.kill();
      } catch {
        // best effort
      }
    }, 30_000);
    timeout.unref();
    try {
      const [stdout, stderr, exitCode] = await Promise.all([
        new Response(child.stdout).text().catch(() => ""),
        new Response(child.stderr).text().catch(() => ""),
        child.exited,
      ]);

      assert.equal(exitCode, 42, stderr || stdout);
      assert.equal(stdout.includes("mode=launch"), true, stdout);
      assert.equal(stdout.includes("sourceName=codex"), true, stdout);
      assert.equal(stdout.includes("separator=--"), true, stdout);
      assert.equal(stdout.includes("arg[0]=--sentinel"), true, stdout);
      assert.equal(stdout.includes("arg[1]=one"), true, stdout);
      assert.equal(stdout.includes("arg[2]=two three"), true, stdout);
    } finally {
      clearTimeout(timeout);
    }
  });
});

function seedCachedNpmPackage(
  home: string,
  spec: { tool: string; package: string; bin: string },
  version: string,
  scriptContent: string,
): void {
  const cacheHome = join(home, ".cache");
  const toolCache = join(cacheHome, "npm-tools", spec.tool);
  const packageKey = new Bun.CryptoHasher("sha256").update(spec.package).digest("hex").slice(0, 16);
  const packageCache = join(toolCache, "packages", packageKey);
  const versionDir = join(packageCache, "versions", version);
  const binDir = join(versionDir, "node_modules", ".bin");
  const pkgDir = join(versionDir, "node_modules", ...spec.package.split("/"));
  mkdirSync(binDir, { recursive: true });
  mkdirSync(pkgDir, { recursive: true });
  writeFileSync(join(pkgDir, "package.json"), JSON.stringify({ name: spec.package, version }));
  const executable = join(binDir, spec.bin);
  writeFileSync(executable, scriptContent, { mode: 0o755 });
  const currentLink = join(packageCache, "current");
  symlinkSync(join("versions", version), currentLink);
}

async function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "agents-integration-"));
  try {
    return await fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function makeFixture(root: string): string {
  const home = join(root, "ts-home");
  mkdirSync(join(home, ".config", "agents"), { recursive: true });
  const syncSource = join(home, ".config", "agents", "sync");
  mkdirSync(syncSource, { recursive: true });
  cpSync(join(SYNC_ROOT, "src"), join(syncSource, "src"), { recursive: true });
  for (const file of ["package.json", "tsconfig.json", "bun.lock"]) {
    copyFileSync(join(SYNC_ROOT, file), join(syncSource, file));
  }
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
  mkdirSync(join(home, ".config", "agents", "tools", "mcporter"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "summarize"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "cliproxyapi"), { recursive: true });
  seedRuntimeRelease(home);
  writeFixtureFiles(home);
  return home;
}

function writeFixtureFiles(home: string): void {
  writeDeployment(home);
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

  writeFileSync(
    join(home, ".codex", "config.toml"),
    'base_url = "http://old-gateway.example.test/v1"\n',
  );
  writeFileSync(
    join(home, ".config", "opencode", "opencode.jsonc"),
    '"baseURL": "http://old-gateway.example.test/v1"\n',
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

async function runSyncProcess(
  home: string,
  args: readonly string[] = [],
  options: {
    readonly env?: Record<string, string>;
    readonly timeoutMs?: number;
  } = {},
): Promise<RunResult> {
  const child = Bun.spawn(["bun", TS_SYNC, ...args], {
    cwd: SYNC_ROOT,
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
    killSignal: "SIGKILL",
    env: {
      ...Bun.env,
      HOME: home,
      XDG_CACHE_HOME: join(home, ".cache"),
      PATH: PRISTINE_PATH,
      ...sharedToolCacheEnv,
      ...options.env,
    },
  });

  const timeout = setTimeout(() => {
    try {
      child.kill();
    } catch {
      // best effort
    }
  }, options.timeoutMs ?? 30_000);
  timeout.unref();
  try {
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text().catch(() => ""),
      new Response(child.stderr).text().catch(() => ""),
      child.exited,
    ]);
    return { exitCode, stdout, stderr };
  } finally {
    clearTimeout(timeout);
  }
}

async function runWrapper(
  wrapperPath: string,
  args: readonly string[] = [],
  options: {
    readonly home: string;
    readonly env?: Record<string, string>;
    readonly timeoutMs?: number;
  },
): Promise<RunResult> {
  const child = Bun.spawn([wrapperPath, ...args], {
    cwd: options.home,
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
    killSignal: "SIGKILL",
    env: {
      ...Bun.env,
      HOME: options.home,
      XDG_CACHE_HOME: join(options.home, ".cache"),
      PATH: PRISTINE_PATH,
      ...sharedToolCacheEnv,
      ...options.env,
    },
  });

  const timeout = setTimeout(() => {
    try {
      child.kill();
    } catch {
      // best effort
    }
  }, options.timeoutMs ?? 30_000);
  timeout.unref();
  try {
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text().catch(() => ""),
      new Response(child.stderr).text().catch(() => ""),
      child.exited,
    ]);
    return { exitCode, stdout, stderr };
  } finally {
    clearTimeout(timeout);
  }
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
    ".local/share/agents/sync-managed",
    ".local/share/agents/pi-packages",
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
  const normalizedPath = relative.split(sep).join("/");
  if (stat.isSymbolicLink()) {
    out.push({ path: normalizedPath, kind: "symlink" });
    return;
  }
  if (stat.isDirectory()) {
    out.push({ path: normalizedPath, kind: "dir" });
    const children = readdirSync(absolute).toSorted();
    for (const child of children) {
      walk(join(absolute, child), relative ? `${relative}/${child}` : child, out);
    }
    return;
  }
  out.push({
    path: normalizedPath,
    kind: "file",
    content: readFileSync(absolute, "utf8"),
  });
}
