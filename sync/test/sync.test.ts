import { afterEach, beforeEach, type Mock, spyOn, test } from "bun:test";
import assert from "node:assert/strict";
import {
  chmodSync,
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
import { basename, join, resolve } from "node:path";
import { harnessInstructionTarget, harnessSourceRoot, SyncEnv } from "@core/harness.ts";
import { parseTimeoutSeconds, runSync } from "@core/index.ts";
import { runJobsWithPreserve } from "@core/jobs.ts";
import {
  loadRecordedEntryNames,
  planManagedEntries,
  writeRecordedEntryNames,
} from "@core/managed-state.ts";
import { buildSyncPlan, type Job } from "@core/plan.ts";
import { iterExtensionPackages, runInstall } from "@extensions/install.ts";
import {
  extractImportSpecifiers,
  missingPackageRoots,
  packageCacheDir,
  packageHasBuildScript,
  packageIsHealthy,
  patchRuntimeSettings,
  readPackageManifest,
} from "@packages/index.ts";
import { clonePackageWithRunner } from "@packages/source.ts";
import { isErrno } from "@runtime/errors.ts";
import { runCommandOutcome, runProcess } from "@runtime/process.ts";
import { seedRuntimeRelease, sharedToolCacheEnv } from "./support/cache-env.ts";

const SYNC_ROOT = resolve(import.meta.dir, "..");
const SRC_ROOT = join(SYNC_ROOT, "src");

let errorSpy: Mock<(...args: unknown[]) => void>;
beforeEach(() => {
  errorSpy = spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => errorSpy.mockRestore());

async function withTempDir<T>(fn: (root: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "agents-tests-"));
  try {
    return await fn(root);
  } finally {
    rmSafe(root);
  }
}

function rmSafe(path: string): void {
  rmSync(path, { recursive: true, force: true });
}

function writeFile(path: string, content: string): void {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, content);
}

function writeExecutable(path: string, script: string): void {
  writeFile(path, script);
  chmodSync(path, 0o755);
}

function isGone(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return false;
  } catch (error) {
    return isErrno(error, "ESRCH");
  }
}

function initGitRepo(path: string): void {
  runGit(path, ["init"]);
  runGit(path, ["config", "user.name", "Test User"]);
  runGit(path, ["config", "user.email", "test@example.com"]);
  runGit(path, ["add", "."]);
  runGit(path, ["commit", "-m", "init"]);
}

function runGit(cwd: string, args: string[]): void {
  const result = Bun.spawnSync(["git", ...args], {
    cwd,
    stdout: "pipe",
    stderr: "pipe",
  });
  assert.equal(result.exitCode, 0, result.stderr.toString() || result.stdout.toString());
}

const readText = (path: string): string => readFileSync(path, "utf8");

const exists = (path: string): boolean => existsSync(path);

const TEST_CLIPROXY_DEPLOYMENT = {
  server: { hostname: hostname() },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
} as const;

test("run_jobs_with_preserve_renders_secret_template_idempotently", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "runtime", "config.yaml");
    const secretsPath = join(root, "secrets.local.json");
    writeFile(src, `api-key: \${API_KEY}\n`);
    writeFile(secretsPath, `${JSON.stringify({ API_KEY: 'quoted"value' })}\n`);

    const jobs: Job[] = [{ src, dst, kind: "SecretTemplate", secretsPath }];
    assert.equal(await runJobsWithPreserve(jobs), true);
    assert.equal(readText(dst), `api-key: ${JSON.stringify('quoted"value')}\n`);
    assert.equal(lstatSync(dst).mode & 0o777, 0o600);

    const first = lstatSync(dst);
    assert.equal(await runJobsWithPreserve(jobs), true);
    const second = lstatSync(dst);
    assert.equal(second.ino, first.ino);
    assert.equal(second.mtimeMs, first.mtimeMs);
  });
});

test("run_jobs_with_preserve_skips_secret_template_without_local_secrets", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "config.yaml");
    writeFile(src, `api-key: \${API_KEY}\n`);
    writeFile(dst, "keep\n");

    assert.equal(
      await runJobsWithPreserve([
        {
          src,
          dst,
          kind: "SecretTemplate",
          secretsPath: join(root, "missing-secrets.json"),
        },
      ]),
      true,
    );
    assert.equal(readText(dst), "keep\n");
  });
});

test("run_jobs_with_preserve_rejects_missing_template_secret", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "config.yaml");
    const secretsPath = join(root, "secrets.local.json");
    writeFile(src, `api-key: \${API_KEY}\n`);
    writeFile(dst, "keep\n");
    writeFile(secretsPath, "{}\n");

    assert.equal(
      await runJobsWithPreserve([{ src, dst, kind: "SecretTemplate", secretsPath }]),
      false,
    );
    assert.equal(readText(dst), "keep\n");
  });
});

test("run_jobs_with_preserve_expands_cliproxy_credential_pools_idempotently", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "config.yaml");
    const secretsPath = join(root, "secrets.local.json");
    writeFile(
      src,
      `remote-management:
  allow-remote: true
  secret-key: tailnet
codex-api-key:
  - x-credential-pool: opencode-go
    prefix: go
    base-url: https://example.test/v1
openai-compatibility:
  - x-credential-pool: deepseek
    name: deepseek
    base-url: https://deepseek.example/v1
`,
    );
    writeFile(
      secretsPath,
      `${JSON.stringify({
        CLIPROXY_CREDENTIAL_POOLS: {
          "opencode-go": [
            { apiKey: "go-one", weight: 1 },
            { apiKey: "go-two", weight: 2 },
          ],
          deepseek: [{ apiKey: "router-one", weight: 1 }],
        },
      })}\n`,
    );

    const jobs: Job[] = [
      {
        src,
        dst,
        kind: "CliProxyConfig",
        secretsPath,
        deployment: TEST_CLIPROXY_DEPLOYMENT,
      },
    ];
    assert.equal(await runJobsWithPreserve(jobs), true);
    const config = Bun.YAML.parse(readText(dst)) as Record<
      string,
      Record<string, unknown> | unknown[]
    >;
    assert.equal((config["remote-management"] as Record<string, unknown>)["secret-key"], "tailnet");
    assert.equal("api-keys" in config, false);
    assert.deepEqual(
      (config["codex-api-key"] as Array<Record<string, unknown>>).map((entry) => ({
        apiKey: entry["api-key"],
        weight: entry["weight"],
        poolMarker: entry["x-credential-pool"],
      })),
      [
        { apiKey: "go-one", weight: 1, poolMarker: undefined },
        { apiKey: "go-two", weight: 2, poolMarker: undefined },
      ],
    );
    assert.deepEqual(
      (config["openai-compatibility"] as Array<Record<string, unknown>>)[0]!["api-key-entries"],
      [{ "api-key": "router-one", weight: 1 }],
    );
    assert.equal(lstatSync(dst).mode & 0o777, 0o600);

    const first = lstatSync(dst);
    assert.equal(await runJobsWithPreserve(jobs), true);
    const second = lstatSync(dst);
    assert.equal(second.ino, first.ino);
    assert.equal(second.mtimeMs, first.mtimeMs);
  });
});

test("run_jobs_with_preserve_rejects_duplicate_cliproxy_credentials", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "config.yaml.tmpl");
    const dst = join(root, "config.yaml");
    const secretsPath = join(root, "secrets.local.json");
    writeFile(
      src,
      `codex-api-key:
  - x-credential-pool: opencode-go
`,
    );
    writeFile(dst, "keep\n");
    writeFile(
      secretsPath,
      `${JSON.stringify({
        CLIPROXY_CREDENTIAL_POOLS: {
          "opencode-go": [{ apiKey: "duplicate" }, { apiKey: "duplicate" }],
        },
      })}\n`,
    );

    assert.equal(
      await runJobsWithPreserve([
        {
          src,
          dst,
          kind: "CliProxyConfig",
          secretsPath,
          deployment: TEST_CLIPROXY_DEPLOYMENT,
        },
      ]),
      false,
    );
    assert.equal(readText(dst), "keep\n");
  });
});

test("run_jobs_with_preserve_keeps_generated_extension_entries", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "src");
    const dst = join(root, "dst");

    writeFile(join(src, "extensions", "context", "index.ts"), "export const live = true;\n");
    writeFile(join(dst, "extensions", "stale.ts"), "stale\n");
    writeFile(join(dst, "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(join(dst, "extensions", "node_modules", "dep", "index.js"), "module.exports = 1;\n");

    const result = await runJobsWithPreserve(
      [{ src, dst, kind: "Dir" }],
      new Map([[dst, ["extensions/package.json", "extensions/node_modules"]]]),
    );

    assert.equal(result, true);
    assert.equal(exists(join(dst, "extensions", "context", "index.ts")), true);
    assert.equal(exists(join(dst, "extensions", "stale.ts")), false);
    assert.equal(exists(join(dst, "extensions", "package.json")), true);
    assert.equal(exists(join(dst, "extensions", "node_modules", "dep", "index.js")), true);
  });
});

test("run_jobs_with_preserve_invalidates_cache_after_source_rewrite", async () => {
  await withTempDir(async (root) => {
    const sourceOne = join(root, "source-one");
    const firstDestination = join(root, "first-destination");
    const sourceTwo = join(root, "source-two");
    const finalDestination = join(root, "final-destination");

    writeFile(join(sourceOne, "shared.txt"), "old\n");
    writeFile(join(firstDestination, "shared.txt"), "xxx\n");
    writeFile(join(sourceTwo, "shared.txt"), "new\n");

    const result = await runJobsWithPreserve([
      {
        src: sourceOne,
        dst: firstDestination,
        kind: "Dir",
        scope: "Tree",
      },
      {
        src: sourceTwo,
        dst: sourceOne,
        kind: "Dir",
        scope: "Children",
      },
      {
        src: sourceOne,
        dst: finalDestination,
        kind: "Dir",
        scope: "Tree",
      },
    ]);

    assert.equal(result, true);
    assert.equal(readText(join(finalDestination, "shared.txt")), "new\n");
  });
});

test("iter_extension_packages_skips_node_modules", async () => {
  await withTempDir(async (root) => {
    writeFile(join(root, "a", "package.json"), "{}");
    writeFile(join(root, "a", "nested", "package.json"), "{}");
    writeFile(join(root, "a", "node_modules", "skip", "package.json"), "{}");

    const packages = [...(await iterExtensionPackages(root))].toSorted();
    assert.equal(packages.length, 2);
  });
});

test("run_install_handles_success_failure_and_timeout", async () => {
  await withTempDir(async (root) => {
    const bin = join(root, "bin");
    mkdirSync(bin, { recursive: true });

    const ok = join(bin, "ok");
    writeExecutable(ok, "#!/bin/sh\nexit 0\n");
    assert.equal(await runInstall([ok], root, 1000), true);

    const fail = join(bin, "fail");
    writeExecutable(fail, "#!/bin/sh\necho bad >&2\nexit 3\n");
    assert.equal(await runInstall([fail], root, 1000), false);

    const sleepy = join(bin, "sleepy");
    writeExecutable(sleepy, "#!/bin/sh\nsleep 2\n");
    assert.equal(await runInstall([sleepy], root, 100), false);
  });
});

test("run_command_outcome_resolves_relative_executable_from_command_cwd", async () => {
  await withTempDir(async (root) => {
    const scriptDir = join(root, "scripts");
    mkdirSync(scriptDir, { recursive: true });

    const command = "./scripts/ok";
    writeExecutable(join(scriptDir, "ok"), "#!/bin/sh\nexit 0\n");

    assert.deepEqual(await runCommandOutcome([command], root, 1000), {
      _tag: "Success",
    });
  });
});

test("run_command_outcome_times_out_cross_platform", async () => {
  await withTempDir(async (root) => {
    const startedAt = performance.now();
    const outcome = await runCommandOutcome(
      ["bun", "-e", "setInterval(() => {}, 1000)"],
      root,
      100,
    );
    const elapsed = performance.now() - startedAt;

    assert.deepEqual(outcome, { _tag: "TimedOut" });
    assert.equal(elapsed < 1000, true);
  });
});
test("process_timeout_sleeping_fake_uv", async () => {
  await withTempDir(async (root) => {
    const bin = join(root, "bin");
    mkdirSync(bin, { recursive: true });
    const fakeUv = join(bin, "uv");
    writeExecutable(fakeUv, "#!/bin/sh\necho 'fake uv $1 $2' >&2\nsleep 30\n");

    const originalPath = process.env["PATH"];
    process.env["PATH"] = `${bin}:${originalPath ?? ""}`;
    try {
      const startedAt = performance.now();
      const result = await runProcess(["uv", "python", "install"], { timeoutMs: 100 });
      const elapsed = performance.now() - startedAt;
      assert.equal(result.timedOut, true);
      assert.equal(elapsed < 1000, true, `elapsed ${elapsed}ms`);
    } finally {
      process.env["PATH"] = originalPath ?? "";
    }
  });
});

test("process_inherit_preserves_terminal_stdin", async () => {
  if (!process.stdin.isTTY) {
    return;
  }

  const result = await runProcess(["sh", "-c", "test -t 0"], { stdio: "inherit" });

  assert.equal(result.exitCode, 0);
});

test("process_timeout_kills_descendant_holding_stdout", async () => {
  await withTempDir(async (root) => {
    const fixture = join(root, "descendant.ts");
    writeFileSync(
      fixture,
      [
        `import { spawn } from "node:child_process";`,
        `console.log("parent " + process.pid);`,
        `const child = spawn("sh", ["-c", "while :; do sleep 1; done"], {`,
        `  stdio: ["ignore", "inherit", "inherit"],`,
        `  detached: false,`,
        `});`,
        `child.unref();`,
        `if (child.pid) {`,
        `  console.log("child " + child.pid);`,
        `}`,
        `setInterval(() => {}, 10_000);`,
      ].join("\n"),
      "utf8",
    );

    const startedAt = performance.now();
    const result = await runProcess(["bun", "run", fixture], { timeoutMs: 500, stdio: "pipe" });
    const elapsed = performance.now() - startedAt;

    assert.equal(result.timedOut, true);
    assert.equal(elapsed < 2_000, true, `elapsed ${elapsed}ms`);

    const parentMatch = result.stdout.match(/parent (\d+)/);
    const childMatch = result.stdout.match(/child (\d+)/);
    assert.ok(parentMatch, `missing parent pid in stdout: ${result.stdout}`);
    assert.ok(childMatch, `missing child pid in stdout: ${result.stdout}`);
    const parentPid = Number(parentMatch[1]);
    const childPid = Number(childMatch[1]);

    assert.equal(isGone(parentPid), true, `parent ${parentPid} still alive`);
    assert.equal(isGone(childPid), true, `child ${childPid} still alive`);
  });
});

test("run_install_force_kills_term_trapping_process", async () => {
  await withTempDir(async (root) => {
    const bin = join(root, "bin");
    mkdirSync(bin, { recursive: true });

    const trapped = join(bin, "trapped");
    writeExecutable(trapped, "#!/bin/sh\ntrap '' TERM\nwhile :; do sleep 1; done\n");

    const helper = join(root, "helper.ts");
    writeFileSync(
      helper,
      `import { runInstall } from ${JSON.stringify(join(SRC_ROOT, "extensions", "install.ts"))};
const result = await runInstall([${JSON.stringify(trapped)}], ${JSON.stringify(root)}, 100);
console.log(String(result));
`,
    );

    const result = Bun.spawnSync(["bun", helper], {
      cwd: SYNC_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...Bun.env,
        PATH: Bun.env["PATH"] ?? "",
      },
    });

    assert.equal(result.exitCode, 0, result.stderr.toString() || result.stdout.toString());
    assert.equal(result.stdout.toString().trim(), "false");
  });
});
test("python bootstrap times out sleeping fake uv", async () => {
  await withTempDir(async (root) => {
    const bin = join(root, "bin");
    mkdirSync(bin, { recursive: true });
    const fakeUv = join(bin, "uv");
    writeExecutable(fakeUv, "#!/bin/sh\nsleep 30\n");

    const originalPath = process.env["PATH"];
    process.env["PATH"] = `${bin}:${originalPath ?? ""}`;
    try {
      const syncEnv = makeSyncEnv(root, 100);
      const startedAt = performance.now();
      const success = await runSync(syncEnv);
      const elapsed = performance.now() - startedAt;

      assert.equal(elapsed < 2_000, true, `elapsed ${elapsed}ms`);
      assert.equal(
        errorSpy.mock.calls.some(
          ([msg]) => typeof msg === "string" && msg.includes("uv python install failed"),
        ),
        true,
      );
      assert.equal(success, true);
    } finally {
      process.env["PATH"] = originalPath ?? "";
    }
  });
});

test("main_reports_lock_contention_and_skips", async () => {
  await withTempDir(async (root) => {
    const helper = join(root, "helper.ts");
    writeFileSync(
      helper,
      `import { SyncEnv } from ${JSON.stringify(join(SRC_ROOT, "core", "harness.ts"))};
        import { main, tryAcquireSyncLock } from ${JSON.stringify(join(SRC_ROOT, "core", "index.ts"))};

const syncEnv = SyncEnv.fromHome(${JSON.stringify(root)}, 1_000);
const lock = tryAcquireSyncLock(syncEnv);
if (!lock) {
  process.exit(2);
}
const exit = await main();
console.log(String(exit));
`,
    );

    const result = Bun.spawnSync(["bun", helper], {
      cwd: SYNC_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...Bun.env,
        HOME: root,
        PATH: Bun.env["PATH"] ?? "",
        ...sharedToolCacheEnv,
      },
    });

    assert.equal(result.exitCode, 0, result.stderr.toString() || result.stdout.toString());
    assert.equal(result.stdout.toString().trim(), "0");
    assert.equal(
      result.stderr.toString().includes("another sync is already running; skipping"),
      true,
    );
  });
});

test("watchdog_exits_124_on_global_timeout", async () => {
  await withTempDir(async (root) => {
    const helper = join(root, "watchdog.ts");
    writeFileSync(
      helper,
      `import { startSyncWatchdog } from ${JSON.stringify(join(SRC_ROOT, "core", "index.ts"))};
startSyncWatchdog(1);
setInterval(() => {}, 1_000);
`,
    );

    const result = Bun.spawnSync(["bun", helper], {
      cwd: SYNC_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...Bun.env,
        PATH: Bun.env["PATH"] ?? "",
      },
    });

    assert.equal(result.exitCode, 124, result.stderr.toString() || result.stdout.toString());
    assert.equal(result.stderr.toString().includes("timed out after 1s"), true);
  });
});
test("watchdog can be cancelled so host outlives short timeout", async () => {
  await withTempDir(async (root) => {
    const helper = join(root, "watchdog-cancel.ts");
    writeFileSync(
      helper,
      [
        `import { startSyncWatchdog } from ${JSON.stringify(join(SRC_ROOT, "core", "index.ts"))};`,
        `const stop = startSyncWatchdog(1);`,
        `await Bun.sleep(500);`,
        `stop();`,
        `setTimeout(() => console.log("ok"), 2_000);`,
      ].join("\n"),
      "utf8",
    );

    const result = Bun.spawnSync(["bun", helper], {
      cwd: SYNC_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...Bun.env,
        PATH: Bun.env["PATH"] ?? "",
      },
    });

    assert.equal(result.exitCode, 0, result.stderr.toString() || result.stdout.toString());
    assert.equal(result.stdout.toString().trim(), "ok");
  });
});

test("parse_timeout_seconds_uses_default_for_invalid_values", async () => {
  assert.equal(parseTimeoutSeconds(undefined, 7), 7);
  assert.equal(parseTimeoutSeconds("0", 7), 7);
  assert.equal(parseTimeoutSeconds("nope", 7), 7);
  assert.equal(parseTimeoutSeconds("9", 7), 9);
});

test("sync_env_harness_lookup_is_typed", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);

    const pi = syncEnv.harness("pi");
    assert.ok(pi);
    assert.equal(
      harnessSourceRoot(pi!, syncEnv.harnessesHome),
      join(root, ".config", "agents", "harnesses", "pi", "agent"),
    );
    assert.equal(harnessInstructionTarget(pi!), join(root, ".pi", "agent", "AGENTS.md"));
  });
});

test("sync_plan_resolves_hook_targets_from_harness_specs", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const syncPlan = buildSyncPlan(syncEnv) as unknown as { hooks: Record<string, unknown>[] };

    const packageHook = syncPlan.hooks.find((hook) => hook["kind"] === "PackageBootstrap");
    const extensionHooks = syncPlan.hooks.filter((hook) => hook["kind"] === "ExtensionDeps");

    assert.ok(packageHook);
    assert.equal(
      packageHook!["manifestPath"],
      join(root, ".config", "agents", "harnesses", "pi", "agent", "packages.json"),
    );
    assert.equal(packageHook!["runtimeSettingsPath"], join(root, ".pi", "agent", "settings.json"));
    assert.equal(packageHook!["cacheRoot"], join(root, ".local", "share", "agents", "pi-packages"));

    assert.deepEqual(
      extensionHooks.map((hook) => [(hook["harness"] as { id: string }).id, hook["root"]]),
      [
        ["opencode", join(root, ".config", "opencode")],
        ["pi", join(root, ".pi", "agent", "extensions")],
        ["omp", join(root, ".omp", "agent")],
      ],
    );
  });
});

test("sync_plan_deploys_cliproxy_panel_asset_only_on_gateway_host", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const panelSrc = join(root, ".config", "agents", "tools", "cliproxyapi", "panel.html");
    writeFile(panelSrc, "<html>panel</html>\n");
    const panelDst = join(".cli-proxy-api", "static", "management.html");

    const gatewayPlan = buildSyncPlan(syncEnv) as unknown as {
      jobs: { kind: string; src?: string; dst?: string }[];
    };
    const panelJob = gatewayPlan.jobs.find(
      (job) => job.kind === "File" && job.dst?.endsWith(panelDst),
    );
    assert.equal(panelJob?.src, panelSrc);

    writeFile(
      join(root, ".config", "agents", "tools", "cliproxyapi", "deployment.json"),
      `${JSON.stringify({
        ...TEST_CLIPROXY_DEPLOYMENT,
        server: { hostname: "not-the-gateway.example.test" },
      })}\n`,
    );
    const clientPlan = buildSyncPlan(syncEnv) as unknown as {
      jobs: { kind: string; src?: string; dst?: string }[];
    };
    assert.equal(
      clientPlan.jobs.some((job) => job.kind === "File" && job.dst?.endsWith(panelDst)),
      false,
    );
  });
});

test("run_sync_happy_path", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);

    writeFile(join(root, ".config", "agents", "HARNESS.md"), "agent-instructions");
    writeFile(join(root, ".config", "agents", "tools", "mcporter", "mcporter.jsonc"), '{"x":1}');
    writeFile(
      join(root, ".config", "agents", "tools", "summarize", "config.json"),
      '{"model":"fast"}',
    );
    writeFile(join(root, ".config", "agents", "skills", "current", "skill.txt"), "skill-content");
    writeFile(join(root, ".config", "agents", "harnesses", "codex", "config.toml"), "codex = true");
    writeFile(
      join(root, ".config", "agents", "harnesses", "omp", "agent", "config.yml"),
      "theme:\n  dark: graphite\n",
    );
    writeFile(
      join(
        root,
        ".config",
        "agents",
        "harnesses",
        "pi",
        "agent",
        "extensions",
        "answer",
        "package.json",
      ),
      "{}",
    );
    mkdirSync(
      join(
        root,
        ".config",
        "agents",
        "harnesses",
        "pi",
        "agent",
        "extensions",
        "answer",
        "node_modules",
      ),
      {
        recursive: true,
      },
    );
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "stale.ts"), "stale");
    writeFile(join(root, ".omp", "agent", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".omp", "agent", "logs", "keep.txt"), "keep-me");

    assert.equal(await runSync(syncEnv), true);
    assert.equal(exists(join(root, ".codex", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".config", "opencode", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".pi", "agent", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".omp", "agent", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".omp", "agent", "config.yml")), true);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".mcporter", "mcporter.json")), true);
    assert.equal(exists(join(root, ".summarize", "config.json")), true);
    assert.equal(exists(join(root, ".pi", "agent", "auth.json")), true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "stale.ts")), false);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "stale.txt")), false);
    assert.equal(exists(join(root, ".omp", "agent", "logs", "keep.txt")), true);
  });
});

test("run_sync_missing_sources_is_non_fatal", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    assert.equal(await runSync(syncEnv), true);
  });
});

test("run_sync_cleans_managed_entries_for_multiple_harnesses", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "skills", "current", "skill.txt"), "fresh-skill");
    writeFile(join(agentsRoot, "harnesses", "codex", "config.toml"), "fresh = true\n");
    writeFile(
      join(agentsRoot, "harnesses", "omp", "agent", "config.yml"),
      "theme:\n  light: graphite\n",
    );

    writeFile(join(root, ".codex", "config.toml"), "stale = true\n");
    writeFile(join(root, ".codex", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".codex", "logs", "keep.txt"), "keep-me");
    writeFile(join(root, ".omp", "agent", "config.yml"), "stale-config\n");
    writeFile(join(root, ".omp", "agent", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".omp", "agent", "logs", "keep.txt"), "keep-me");

    assert.equal(await runSync(syncEnv), true);
    assert.equal(readText(join(root, ".codex", "config.toml")), "fresh = true\n");
    assert.equal(
      readText(join(root, ".omp", "agent", "config.yml")),
      "theme:\n  light: graphite\n",
    );
    assert.equal(exists(join(root, ".codex", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".codex", "skills", "stale.txt")), false);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "stale.txt")), false);
    assert.equal(exists(join(root, ".codex", "logs", "keep.txt")), true);
    assert.equal(exists(join(root, ".omp", "agent", "logs", "keep.txt")), true);
  });
});

test("run_sync_omp_cleans_managed_entries_but_preserves_local_files", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "skills", "current", "skill.txt"), "fresh-skill");
    writeFile(
      join(agentsRoot, "harnesses", "omp", "agent", "config.yml"),
      "theme:\n  light: graphite\n",
    );

    writeFile(join(root, ".omp", "agent", "config.yml"), "stale-config\n");
    writeFile(join(root, ".omp", "agent", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".omp", "agent", "logs", "keep.txt"), "keep-me");

    assert.equal(await runSync(syncEnv), true);
    assert.equal(
      readText(join(root, ".omp", "agent", "config.yml")),
      "theme:\n  light: graphite\n",
    );
    assert.equal(exists(join(root, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "stale.txt")), false);
    assert.equal(exists(join(root, ".omp", "agent", "logs", "keep.txt")), true);
  });
});

test("run_sync_cleans_legacy_pi_entries_without_prior_state", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(join(root, ".pi", "agent", "legacy", "old.txt"), "stale");
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');

    assert.equal(await runSync(syncEnv), true);
    assert.equal(exists(join(root, ".pi", "agent", "legacy")), false);
    assert.equal(exists(join(root, ".pi", "agent", "auth.json")), true);
  });
});

test("run_sync_removes_entries_removed_from_ssot_after_prior_sync", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");
    const codexConfig = join(agentsRoot, "harnesses", "codex", "config.toml");
    const skillsRoot = join(agentsRoot, "skills", "current");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(join(skillsRoot, "skill.txt"), "fresh-skill");
    writeFile(codexConfig, "fresh = true\n");

    assert.equal(await runSync(syncEnv), true);
    assert.equal(exists(join(root, ".codex", "config.toml")), true);
    assert.equal(exists(join(root, ".codex", "skills", "skill.txt")), true);
    assert.equal(
      exists(join(root, ".local", "share", "agents", "sync-managed", "codex.json")),
      true,
    );

    rmSync(codexConfig, { force: true });
    rmSync(skillsRoot, { recursive: true, force: true });
    writeFile(join(root, ".codex", "logs", "keep.txt"), "keep-me");

    assert.equal(await runSync(syncEnv), true);
    assert.equal(exists(join(root, ".codex", "config.toml")), false);
    assert.equal(exists(join(root, ".codex", "skills")), false);
    assert.equal(exists(join(root, ".codex", "logs", "keep.txt")), true);
  });
});

test("run_sync_removes_cli_proxy_api_wrapper_after_gateway_to_client_transition", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    const arch = process.arch === "arm64" || process.arch === "x64" ? process.arch : "arm64";
    const platformKey = `${process.platform}-${arch}`;
    const version = "7.2.132";
    const repository = "router-for-me/CLIProxyAPI";
    const assetName = "CLIProxyAPI_fixture.tar.gz";
    const checksum = new Bun.CryptoHasher("sha256").update("fixture archive").digest("hex");
    const installDir = join(
      root,
      "cache",
      "github-tools",
      "cliproxyapi",
      "versions",
      version,
      platformKey,
    );
    const wrapperPath = join(root, ".local", "bin", "cli-proxy-api");
    const wrappersStatePath = join(
      root,
      ".local",
      "share",
      "agents",
      "sync-managed",
      "wrappers.json",
    );

    writeFile(
      join(agentsRoot, "tools", "cliproxyapi", "release.json"),
      `${JSON.stringify(
        {
          repository,
          version,
          binary: "cli-proxy-api",
          assets: { [platformKey]: { name: assetName, sha256: checksum } },
        },
        null,
        2,
      )}\n`,
    );
    writeExecutable(join(installDir, "cli-proxy-api"), "#!/bin/sh\nexit 0\n");
    writeFile(
      join(installDir, "receipt.json"),
      `${JSON.stringify({ repository, version, asset: assetName, sha256: checksum }, null, 2)}\n`,
    );
    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "skills", "current", "skill.txt"), "fresh-skill");
    writeFile(join(agentsRoot, "harnesses", "codex", "config.toml"), "fresh = true\n");

    const previousCacheHome = process.env["XDG_CACHE_HOME"];
    process.env["XDG_CACHE_HOME"] = join(root, "cache");
    try {
      assert.equal(await runSync(syncEnv), true);
      assert.equal(exists(wrapperPath), true);
      assert.equal(readText(wrappersStatePath).includes(wrapperPath), true);

      writeFile(
        join(agentsRoot, "tools", "cliproxyapi", "deployment.json"),
        `${JSON.stringify({
          server: { hostname: "different-gateway.example.test" },
          listen: { host: "100.64.0.42", port: 9443 },
          client: { baseUrl: "https://gateway.example.test:9443/v1" },
        })}\n`,
      );

      assert.equal(await runSync(syncEnv), true);
      assert.equal(exists(wrapperPath), false);
      assert.equal(readText(wrappersStatePath).includes(wrapperPath), false);
    } finally {
      if (previousCacheHome === undefined) {
        delete process.env["XDG_CACHE_HOME"];
      } else {
        process.env["XDG_CACHE_HOME"] = previousCacheHome;
      }
    }
  });
});

test("run_sync_copies_current_skills_but_not_legacy_skills", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "skills", "current", "skill.txt"), "fresh-skill");
    writeFile(join(agentsRoot, "skills", "legacy", "old-skill.txt"), "legacy-skill");

    assert.equal(await runSync(syncEnv), true);
    assert.equal(exists(join(root, ".codex", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".codex", "skills", "legacy")), false);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "legacy")), false);
  });
});

test("run_sync_preserves_generated_extension_runtime_when_hook_inputs_match", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const { fingerprintTree } = await import("@core/hook-state.ts");

    writeFile(join(root, ".config", "agents", "HARNESS.md"), "agent-instructions");
    writeFile(
      join(
        root,
        ".config",
        "agents",
        "harnesses",
        "pi",
        "agent",
        "extensions",
        "context",
        "index.ts",
      ),
      "export const live = true;\n",
    );
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(
      join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js"),
      "module.exports = 1;\n",
    );
    writeFile(
      join(root, ".local", "share", "agents", "sync-managed", "pi.extension-deps.json"),
      `${JSON.stringify(
        {
          fingerprint: fingerprintTree(
            join(root, ".config", "agents", "harnesses", "pi", "agent", "extensions"),
          ),
          generatedEntries: ["package.json", "node_modules"],
        },
        null,
        2,
      )}\n`,
    );

    const success = await runSync(syncEnv);
    assert.equal(success, true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package.json")), true);
    assert.equal(
      exists(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js")),
      true,
    );
  });
});

test("run_sync_drops_legacy_npm_extension_state_entries_without_reinstall", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const { fingerprintTree } = await import("@core/hook-state.ts");
    const sourceRoot = join(root, ".config", "agents", "harnesses", "pi", "agent", "extensions");
    const statePath = join(
      root,
      ".local",
      "share",
      "agents",
      "sync-managed",
      "pi.extension-deps.json",
    );

    writeFile(join(root, ".config", "agents", "HARNESS.md"), "agent-instructions");
    writeFile(join(sourceRoot, "context", "index.ts"), "export const live = true;\n");
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(
      join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js"),
      "module.exports = 1;\n",
    );
    writeFile(
      join(root, ".pi", "agent", "extensions", "package-lock.json"),
      '{"lockfileVersion":3}\n',
    );
    writeFile(
      join(root, ".pi", "agent", "extensions", "npm-shrinkwrap.json"),
      '{"lockfileVersion":3}\n',
    );
    writeFile(
      statePath,
      `${JSON.stringify(
        {
          fingerprint: fingerprintTree(sourceRoot),
          generatedEntries: [
            "package.json",
            "node_modules",
            "package-lock.json",
            "npm-shrinkwrap.json",
          ],
        },
        null,
        2,
      )}\n`,
    );

    const success = await runSync(syncEnv);
    assert.equal(success, true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package.json")), true);
    assert.equal(
      exists(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js")),
      true,
    );
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package-lock.json")), false);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "npm-shrinkwrap.json")), false);

    const state = JSON.parse(readText(statePath)) as {
      generatedEntries?: unknown;
    };
    assert.deepEqual(state.generatedEntries, ["package.json", "node_modules"]);
  });
});

test("run_sync_removes_generated_extension_runtime_when_hook_inputs_change", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);

    writeFile(join(root, ".config", "agents", "HARNESS.md"), "agent-instructions");
    writeFile(
      join(
        root,
        ".config",
        "agents",
        "harnesses",
        "pi",
        "agent",
        "extensions",
        "context",
        "index.ts",
      ),
      "export const live = true;\n",
    );
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(
      join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js"),
      "module.exports = 1;\n",
    );
    writeFile(
      join(root, ".local", "share", "agents", "sync-managed", "pi.extension-deps.json"),
      `${JSON.stringify(
        {
          fingerprint: "stale",
          generatedEntries: ["package.json", "node_modules"],
        },
        null,
        2,
      )}\n`,
    );

    const success = await runSync(syncEnv);
    assert.equal(success, true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package.json")), false);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "node_modules")), false);
  });
});

test("run_sync_omp_does_not_bootstrap_packages", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(
      join(agentsRoot, "harnesses", "omp", "agent", "config.yml"),
      "interruptMode: immediate\n",
    );
    writeFile(
      join(agentsRoot, "harnesses", "omp", "agent", "packages.json"),
      "this is not valid json\n",
    );

    assert.equal(await runSync(syncEnv), true);
    assert.equal(
      readText(join(root, ".omp", "agent", "packages.json")),
      "this is not valid json\n",
    );
    assert.equal(exists(join(root, ".omp", "agent", "config.yml")), true);
  });
});

test("run_sync_omp_ignores_runtime_session_sources when inferring dependencies", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "HARNESS.md"), "agent-instructions");
    writeFile(
      join(agentsRoot, "harnesses", "omp", "agent", "config.yml"),
      "interruptMode: immediate\n",
    );
    writeFile(join(root, ".omp", "agent", "sessions", "poison.ts"), 'import "#sqlite";\n');

    assert.equal(await runSync(syncEnv), true);
    assert.equal(exists(join(root, ".omp", "agent", "package.json")), false);
  });
});

test("extract_import_specifiers_ignores_prose_and_string_literals", async () => {
  const sample = `
import fs from "node:fs";
import { createCommitTools } from "@oh-my-pi/pi-coding-agent";
export { helper } from "external-lib";
const code = 'file.content.includes("rename from ")';
const prose = "from lodash";
const dynamic = await import("dynamic-pkg");
const required = require("req-pkg");
`;
  const extracted = extractImportSpecifiers(sample);
  assert.deepEqual(extracted, [
    "node:fs",
    "@oh-my-pi/pi-coding-agent",
    "external-lib",
    "dynamic-pkg",
    "req-pkg",
  ]);
});

test("missing_package_roots_ignores_invalid_package_names_in_source", async () => {
  await withTempDir(async (root) => {
    const srcDir = join(root, "src");
    mkdirSync(srcDir, { recursive: true });
    writeFileSync(
      join(srcDir, "index.ts"),
      `
import { test } from "@oh-my-pi/pi-coding-agent";
const check = file.content.includes("\\nrename from ") || file.content.startsWith("rename from ");
`,
    );
    const missing = missingPackageRoots(root);
    assert.deepEqual(missing, ["@oh-my-pi/pi-coding-agent"]);
  });
});

test("read_package_manifest_dedupes_sources", async () => {
  await withTempDir(async (root) => {
    const path = join(root, "packages.json");
    writeFile(
      path,
      `{
  "packages": [
    "https://github.com/tintinweb/pi-supervisor",
    "https://github.com/tintinweb/pi-supervisor",
    "https://github.com/joelhooks/pi-tools"
  ]
}`,
    );

    const manifest = readPackageManifest(path);
    assert.equal(manifest.packages.length, 2);
  });
});

test("patch_runtime_settings_preserves_other_keys", async () => {
  await withTempDir(async (root) => {
    const path = join(root, "settings.json");
    writeFile(
      path,
      `{
  "theme": "dark",
  "defaultModel": "gpt-5.4"
}
`,
    );

    patchRuntimeSettings(path, [join(root, "pkg")]);
    const settings = JSON.parse(readText(path)) as {
      theme?: string;
      packages?: string[];
    };
    assert.equal(settings.theme, "dark");
    assert.deepEqual(settings.packages, [join(root, "pkg")]);
  });
});

test("package_cache_dir_is_stable", async () => {
  const root = "/tmp/cache-root";
  const left = packageCacheDir(root, "https://github.com/tintinweb/pi-supervisor");
  const right = packageCacheDir(root, "https://github.com/tintinweb/pi-supervisor");
  assert.equal(left, right);
});

test("package_cache_dir_uses_basename_for_local_paths", async () => {
  const root = "/tmp/cache-root";
  const sources = ["/opt/packages/foo", "/var/tmp/foo/"];

  for (const source of sources) {
    const cacheDir = packageCacheDir(root, source);
    assert.equal(basename(cacheDir).startsWith("foo-"), true, source);
  }
});

test("github_clone_command_prefers_gh_when_available", async () => {
  await withTempDir(async (root) => {
    const target = join(root, "out");
    const attempts: string[][] = [];
    await clonePackageWithRunner(
      "https://github.com/tintinweb/pi-supervisor",
      target,
      true,
      async (command) => {
        attempts.push([...command]);
        return true;
      },
    );
    assert.equal(attempts.length, 1);
    assert.equal(attempts[0]![0], "gh");
    assert.equal(attempts[0]![3], "tintinweb/pi-supervisor");
  });
});

test("github_clone_falls_back_to_git_after_gh_failure", async () => {
  await withTempDir(async (root) => {
    const target = join(root, "out");
    const attempts: string[][] = [];
    const outcomes = [false, true];
    let index = 0;
    const success = await clonePackageWithRunner(
      "https://github.com/tintinweb/pi-supervisor",
      target,
      true,
      async (command) => {
        attempts.push([...command]);
        const outcome = outcomes[index] ?? false;
        index += 1;
        return outcome;
      },
    );

    assert.equal(success, true);
    assert.equal(attempts.length, 2);
    assert.equal(attempts[0]![0], "gh");
    assert.equal(attempts[1]![0], "git");
    assert.equal(attempts[1]![3], "https://github.com/tintinweb/pi-supervisor");
  });
});

test("validate_package_dir_accepts_manifest_and_conventional_dirs", async () => {
  await withTempDir(async (root) => {
    const manifestPkg = join(root, "manifest-pkg");
    writeFile(
      join(manifestPkg, "package.json"),
      `{
  "pi": {
    "extensions": ["./src/index.ts"]
  }
}`,
    );
    writeFile(join(manifestPkg, "src", "index.ts"), "export default {}\n");
    assert.equal(packageIsHealthy(manifestPkg), true);

    const conventionalPkg = join(root, "conventional-pkg");
    writeFile(join(conventionalPkg, "extensions", "index.ts"), "export default {}\n");
    assert.equal(packageIsHealthy(conventionalPkg), true);
  });
});

test("validate_package_dir_detects_missing_import_packages", async () => {
  await withTempDir(async (root) => {
    const pkg = join(root, "import-pkg");
    writeFile(
      join(pkg, "package.json"),
      `{
  "pi": {
    "extensions": ["./index.ts"]
  }
}`,
    );
    writeFile(
      join(pkg, "index.ts"),
      'import { Text } from "@earendil-works/pi-tui";\nexport default Text;\n',
    );
    assert.equal(packageIsHealthy(pkg), false);

    writeFile(join(pkg, "node_modules", "@earendil-works", "pi-tui", "package.json"), "{}\n");
    assert.equal(packageIsHealthy(pkg), true);
  });
});

test("validate_package_dir_rejects_malformed_package_json", async () => {
  await withTempDir(async (root) => {
    const pkg = join(root, "bad-pkg");
    writeFile(join(pkg, "package.json"), "{not valid json");

    assert.throws(() => packageIsHealthy(pkg));
    await assert.rejects(async () => packageHasBuildScript(pkg));
  });
});

test("run_sync_bootstraps_packages_and_patches_runtime_settings", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    writeFile(join(root, ".config", "agents", "HARNESS.md"), "agent-instructions");
    writeFile(join(root, ".pi", "agent", "settings.json"), "{}\n");

    const repos = join(root, "repos");
    mkdirSync(repos, { recursive: true });

    const sourceRepo = join(repos, "source-pkg");
    writeFile(
      join(sourceRepo, "package.json"),
      `{
  "pi": {
    "extensions": ["./src/index.ts"]
  }
}
`,
    );
    writeFile(join(sourceRepo, "src", "index.ts"), "export default {}\n");
    initGitRepo(sourceRepo);

    const buildRepo = join(repos, "build-pkg");
    writeFile(
      join(buildRepo, "package.json"),
      `{
  "scripts": {
    "build": "mkdir -p dist && printf 'export default {}\\n' > dist/index.js"
  },
  "pi": {
    "extensions": ["./dist/index.js"]
  }
}
`,
    );
    initGitRepo(buildRepo);

    writeFile(
      join(root, ".config", "agents", "harnesses", "pi", "agent", "packages.json"),
      `{
  "packages": [
    "${sourceRepo}",
    "${buildRepo}"
  ]
}
`,
    );

    const success = await runSync(syncEnv);
    assert.equal(success, true);
    const settings = readText(join(root, ".pi", "agent", "settings.json"));
    assert.equal(settings.includes("source-pkg"), true);
    assert.equal(settings.includes("build-pkg"), true);
    assert.equal(exists(join(root, ".local", "share", "agents", "pi-packages")), true);
  });
});

test("managed_state_helpers_match_safe_entry_rules", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const harness = syncEnv.harness("codex");
    assert.ok(harness);

    writeFile(
      join(root, ".local", "share", "agents", "sync-managed", "codex.json"),
      `[
  "good.txt",
  "..",
  "/tmp/escape",
  "nested/path",
  "${["..", "outside"].join("/")}",
  "good.txt"
]`,
    );

    const names = loadRecordedEntryNames(
      join(root, ".local", "share", "agents", "sync-managed", "codex.json"),
    );
    assert.deepEqual(names, ["good.txt"]);

    const plan = planManagedEntries(syncEnv);
    assert.ok(plan.harnesses.length > 0);
  });
});

test("managed_state_write_persists_expected_json", async () => {
  await withTempDir(async (root) => {
    const path = join(root, "state", "codex.json");
    writeRecordedEntryNames(path, ["alpha", "beta"]);
    assert.equal(readText(path), '[\n  "alpha",\n  "beta"\n]\n');
  });
});

test("managed_state_identical_json_skips_replacement", async () => {
  await withTempDir(async (root) => {
    const path = join(root, "state", "codex.json");
    const expected = '[\n  "alpha",\n  "beta"\n]\n';

    writeRecordedEntryNames(path, ["alpha", "beta"]);
    const before = lstatSync(path);
    writeRecordedEntryNames(path, ["alpha", "beta"]);
    const after = lstatSync(path);

    assert.equal(readText(path), expected);
    assert.equal(after.ino, before.ino);
    assert.equal(after.mtimeMs, before.mtimeMs);
  });
});

test("managed_state_replaces_identical_symlink", async () => {
  await withTempDir(async (root) => {
    const path = join(root, "state", "codex.json");
    const target = join(root, "target.json");
    const expected = '[\n  "alpha",\n  "beta"\n]\n';

    writeFile(target, expected);
    mkdirSync(join(root, "state"), { recursive: true });
    symlinkSync(target, path);

    writeRecordedEntryNames(path, ["alpha", "beta"]);

    assert.equal(lstatSync(path).isSymbolicLink(), false);
    assert.equal(readText(path), expected);
    assert.equal(readText(target), expected);
  });
});

test("managed_state_malformed_json_is_recoverable", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const statePath = join(root, ".local", "share", "agents", "sync-managed", "codex.json");
    writeFile(statePath, "{not valid json");

    const recovered = loadRecordedEntryNames(statePath);
    assert.deepEqual(recovered, []);

    const plan = planManagedEntries(syncEnv);
    assert.ok(plan.harnesses.length > 0);
  });
});

test("run_sync_prunes_older_complete_releases_after_wrapper_success_and_preserves_unrecognized_dirs", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const releasesRoot = join(root, ".local", "share", "agents", "sync-releases");

    const entries = readdirSync(releasesRoot);
    assert.equal(entries.length, 1);
    const currentReleaseId = entries[0];

    const oldCompleteReleaseId = "0".repeat(64);
    const oldCompleteDir = join(releasesRoot, oldCompleteReleaseId);
    mkdirSync(join(oldCompleteDir, "src"), { recursive: true });
    writeFile(join(oldCompleteDir, "src", "cli.ts"), "console.log('old');");
    mkdirSync(join(oldCompleteDir, "node_modules"), { recursive: true });

    const unrecognizedDir = join(releasesRoot, "unrecognized-custom-dir");
    mkdirSync(unrecognizedDir, { recursive: true });
    writeFile(join(unrecognizedDir, "test.txt"), "data");

    const incompleteShaDir = join(releasesRoot, "1".repeat(64));
    mkdirSync(incompleteShaDir, { recursive: true });
    writeFile(join(incompleteShaDir, "incomplete.txt"), "no node_modules");

    assert.equal(await runSync(syncEnv), true);

    const remaining = readdirSync(releasesRoot);
    assert.equal(remaining.includes(currentReleaseId!), true);
    assert.equal(remaining.includes("unrecognized-custom-dir"), true);
    assert.equal(remaining.includes("1".repeat(64)), true);
    assert.equal(remaining.includes(oldCompleteReleaseId), false);
  });
});

test("run_sync_preserves_previous_releases_if_wrapper_reconciliation_fails", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const releasesRoot = join(root, ".local", "share", "agents", "sync-releases");

    const entries = readdirSync(releasesRoot);
    assert.equal(entries.length, 1);
    const currentReleaseId = entries[0];

    const oldCompleteReleaseId = "0".repeat(64);
    const oldCompleteDir = join(releasesRoot, oldCompleteReleaseId);
    mkdirSync(join(oldCompleteDir, "src"), { recursive: true });
    writeFile(join(oldCompleteDir, "src", "cli.ts"), "console.log('old');");
    mkdirSync(join(oldCompleteDir, "node_modules"), { recursive: true });

    rmSafe(join(root, ".local", "bin"));
    writeFile(join(root, ".local", "bin"), "blocking-file-not-dir");

    assert.equal(await runSync(syncEnv), false);

    const remaining = readdirSync(releasesRoot);
    assert.equal(remaining.includes(oldCompleteReleaseId), true);
    assert.equal(remaining.includes(currentReleaseId!), true);
  });
});
function makeSyncEnv(root: string, installTimeoutMs = 10_000): SyncEnv {
  const agentsRoot = join(root, ".config", "agents");
  const syncSource = join(agentsRoot, "sync");
  mkdirSync(syncSource, { recursive: true });
  cpSync(join(SYNC_ROOT, "src"), join(syncSource, "src"), { recursive: true });
  for (const file of ["package.json", "tsconfig.json", "bun.lock"]) {
    copyFileSync(join(SYNC_ROOT, file), join(syncSource, file));
  }
  seedRuntimeRelease(root);
  writeFile(
    join(agentsRoot, "tools", "cliproxyapi", "deployment.json"),
    `${JSON.stringify(TEST_CLIPROXY_DEPLOYMENT)}\n`,
  );
  for (const id of ["codex", "opencode", "pi", "omp"]) {
    mkdirSync(join(agentsRoot, "harnesses", id), { recursive: true });
  }
  return SyncEnv.fromHome(root, installTimeoutMs);
}
