import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { basename, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { test } from "bun:test";

const SYNC_ROOT = resolve(import.meta.dir, "..");
const SRC_ROOT = join(SYNC_ROOT, "src");

let HarnessId: any;
let SyncEnv: any;
let runSync: any;
let copyItem: any;
let copyDirInto: any;
let iterExtensionPackages: any;
let runInstall: any;
let runCommandOutcome: any;
let parseTimeoutSeconds: any;
let planManagedEntries: any;
let loadRecordedEntryNames: any;
let writeRecordedEntryNames: any;
let readPackageManifest: any;
let patchRuntimeSettings: any;
let packageCacheDir: any;
let githubSlugForTests: any;
let commandForTests: any;
let cloneAttemptsForTests: any;
let validatePackageForTests: any;
let packageHasBuildScript: any;
let main: any;
let tryAcquireSyncLock: any;
let startSyncWatchdog: any;
let buildSyncPlan: any;
let harnessSourceRoot: any;
let harnessInstructionTarget: any;
let runJobsWithPreserve: any;

const runtime = await loadRuntime();
if (!runtime) {
  test.skip("TS runtime modules unavailable yet", () => {});
} else {
  ({
    HarnessId,
    SyncEnv,
    runSync,
    copyItem,
    copyDirInto,
    iterExtensionPackages,
    runInstall,
    runCommandOutcome,
    parseTimeoutSeconds,
    planManagedEntries,
    loadRecordedEntryNames,
    writeRecordedEntryNames,
    readPackageManifest,
    patchRuntimeSettings,
    packageCacheDir,
    githubSlugForTests,
    commandForTests,
    cloneAttemptsForTests,
    validatePackageForTests,
    packageHasBuildScript,
    main,
    tryAcquireSyncLock,
    startSyncWatchdog,
    buildSyncPlan,
    harnessSourceRoot,
    harnessInstructionTarget,
    runJobsWithPreserve,
  } = runtime);
}

function pickFn(
  module: Record<string, unknown>,
  ...names: string[]
): (...args: unknown[]) => unknown {
  for (const name of names) {
    const value = module[name];
    if (typeof value === "function") {
      return value as (...args: unknown[]) => unknown;
    }
  }
  return (..._args: unknown[]) => {
    throw new Error(`missing exported function: ${names.join(" or ")}`);
  };
}

async function loadRuntime(): Promise<Record<string, unknown> | null> {
  const required = [
    "core/index.ts",
    "core/harness.ts",
    "extensions/install.ts",
    "core/jobs.ts",
    "core/managed-state.ts",
    "packages/index.ts",
    "packages/process.ts",
    "packages/validate.ts",
    "runtime/process.ts",
  ];
  if (!required.every((file) => existsSync(join(SRC_ROOT, file)))) {
    return null;
  }

  const [
    libModule,
    harnessModule,
    installModule,
    jobsModule,
    managedModule,
    planModule,
    packagesModule,
    packagesProcessModule,
    runtimeProcessModule,
  ] = await Promise.all([
    import("@core/index.ts"),
    import("@core/harness.ts"),
    import("@extensions/install.ts"),
    import("@core/jobs.ts"),
    import("@core/managed-state.ts"),
    import("@core/plan.ts"),
    import("@packages/index.ts"),
    import("@packages/process.ts"),
    import("@runtime/process.ts"),
  ]);

  return {
    HarnessId: (harnessModule as Record<string, unknown>).HarnessId ??
      (harnessModule as Record<string, unknown>).harnessId,
    SyncEnv: (harnessModule as Record<string, unknown>).SyncEnv,
    harnessSourceRoot: pickFn(
      harnessModule as Record<string, unknown>,
      "harnessSourceRoot",
      "harness_source_root",
    ),
    harnessInstructionTarget: pickFn(
      harnessModule as Record<string, unknown>,
      "harnessInstructionTarget",
      "harness_instruction_target",
    ),
    runSync: pickFn(libModule as Record<string, unknown>, "runSync", "run_sync"),
    copyItem: pickFn(jobsModule as Record<string, unknown>, "copyItem", "copy_item"),
    copyDirInto: pickFn(jobsModule as Record<string, unknown>, "copyDirInto", "copy_dir_into"),
    runJobsWithPreserve: pickFn(
      jobsModule as Record<string, unknown>,
      "runJobsWithPreserve",
      "run_jobs_with_preserve",
    ),
    iterExtensionPackages: pickFn(
      installModule as Record<string, unknown>,
      "iterExtensionPackages",
      "iter_extension_packages",
    ),
    runInstall: pickFn(installModule as Record<string, unknown>, "runInstall", "run_install"),
    runCommandOutcome: pickFn(
      runtimeProcessModule as Record<string, unknown>,
      "runCommandOutcome",
      "run_command_outcome",
    ),
    parseTimeoutSeconds: pickFn(
      libModule as Record<string, unknown>,
      "parseTimeoutSeconds",
      "parse_timeout_seconds",
    ),
    planManagedEntries: pickFn(
      managedModule as Record<string, unknown>,
      "planManagedEntries",
      "plan_managed_entries",
    ),
    loadRecordedEntryNames: pickFn(
      managedModule as Record<string, unknown>,
      "loadRecordedEntryNames",
      "load_recorded_entry_names",
    ),
    writeRecordedEntryNames: pickFn(
      managedModule as Record<string, unknown>,
      "writeRecordedEntryNames",
      "write_recorded_entry_names",
    ),
    readPackageManifest: pickFn(
      packagesModule as Record<string, unknown>,
      "readPackageManifest",
      "read_package_manifest",
    ),
    patchRuntimeSettings: pickFn(
      packagesModule as Record<string, unknown>,
      "patchRuntimeSettings",
      "patch_runtime_settings",
    ),
    packageCacheDir: pickFn(
      packagesModule as Record<string, unknown>,
      "packageCacheDir",
      "package_cache_dir",
    ),
    githubSlugForTests: pickFn(
      packagesModule as Record<string, unknown>,
      "githubSlugForTests",
      "github_slug_for_tests",
    ),
    commandForTests: pickFn(
      packagesModule as Record<string, unknown>,
      "commandForTests",
      "command_for_tests",
    ),
    cloneAttemptsForTests: pickFn(
      packagesModule as Record<string, unknown>,
      "cloneAttemptsForTests",
      "clone_attempts_for_tests",
    ),
    validatePackageForTests: pickFn(
      packagesModule as Record<string, unknown>,
      "validatePackageForTests",
      "validate_package_for_tests",
    ),
    packageHasBuildScript: pickFn(
      packagesModule as Record<string, unknown>,
      "packageHasBuildScript",
      "package_has_build_script",
    ),
    buildSyncPlan: pickFn(
      planModule as Record<string, unknown>,
      "buildSyncPlan",
      "build_sync_plan",
    ),
    main: pickFn(libModule as Record<string, unknown>, "main"),
    tryAcquireSyncLock: pickFn(
      libModule as Record<string, unknown>,
      "tryAcquireSyncLock",
      "try_acquire_sync_lock",
    ),
    startSyncWatchdog: pickFn(
      libModule as Record<string, unknown>,
      "startSyncWatchdog",
      "start_sync_watchdog",
    ),
  };
}

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

function initGitRepo(path: string): void {
  runGit(path, ["init"]);
  runGit(path, ["config", "user.name", "Test User"]);
  runGit(path, ["config", "user.email", "test@example.com"]);
  runGit(path, ["add", "."]);
  runGit(path, ["commit", "-m", "init"]);
}

function runGit(cwd: string, args: string[]): void {
  const result = spawnSync("git", args, {
    cwd,
    encoding: "utf8",
    stdio: "pipe",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
}

const readText = (path: string): string => readFileSync(path, "utf8");

const exists = (path: string): boolean => existsSync(path);

const isPosix = (): boolean => process.platform === "darwin" || process.platform === "linux";

async function call<T>(fn: (...args: unknown[]) => unknown, ...args: unknown[]): Promise<T> {
  return await resolveValue(fn(...args));
}

async function resolveValue<T>(value: unknown): Promise<T> {
  if (
    value &&
    typeof value === "object" &&
    "then" in value &&
    typeof (value as { then?: unknown }).then === "function"
  ) {
    return await (value as Promise<T>);
  }
  return value as T;
}

if (runtime) {
test("copy_item_missing_source_returns_true", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "missing.txt");
    const dst = join(root, "out.txt");
    assert.equal(await call<boolean>(copyItem, src, dst), true);
    assert.equal(exists(dst), false);
  });
});

test("copy_dir_into_merges_existing_destination", async () => {
  await withTempDir(async (root) => {
    const src = join(root, "src");
    const dst = join(root, "dst");
    writeFile(join(src, "x.txt"), "x");
    writeFile(join(dst, "keep.txt"), "k");

    assert.equal(await call<boolean>(copyDirInto, src, dst), true);
    assert.equal(exists(join(dst, "keep.txt")), true);
    assert.equal(exists(join(dst, "x.txt")), true);
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

    const result = await call<boolean>(
      runJobsWithPreserve,
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

test("iter_extension_packages_skips_node_modules", async () => {
  await withTempDir(async (root) => {
    writeFile(join(root, "a", "package.json"), "{}");
    writeFile(join(root, "a", "nested", "package.json"), "{}");
    writeFile(join(root, "a", "node_modules", "skip", "package.json"), "{}");

    const packages = [...(await call<string[]>(iterExtensionPackages, root))].sort();
    assert.equal(packages.length, 2);
  });
});

test("run_install_handles_success_failure_and_timeout", async () => {
  if (!isPosix()) return;

  await withTempDir(async (root) => {
    const bin = join(root, "bin");
    mkdirSync(bin, { recursive: true });

    const ok = join(bin, "ok");
    writeExecutable(ok, "#!/bin/sh\nexit 0\n");
    assert.equal(await call<boolean>(runInstall, [ok], root, 1000), true);

    const fail = join(bin, "fail");
    writeExecutable(fail, "#!/bin/sh\necho bad >&2\nexit 3\n");
    assert.equal(await call<boolean>(runInstall, [fail], root, 1000), false);

    const sleepy = join(bin, "sleepy");
    writeExecutable(sleepy, "#!/bin/sh\nsleep 2\n");
    assert.equal(await call<boolean>(runInstall, [sleepy], root, 100), false);
  });
});

test("run_command_outcome_resolves_relative_executable_from_command_cwd", async () => {
  await withTempDir(async (root) => {
    const scriptDir = join(root, "scripts");
    mkdirSync(scriptDir, { recursive: true });

    const command = process.platform === "win32" ? ".\\scripts\\ok" : "./scripts/ok";
    if (process.platform === "win32") {
      writeFile(join(scriptDir, "ok.cmd"), "@echo off\r\nexit /b 0\r\n");
    } else {
      writeExecutable(join(scriptDir, "ok"), "#!/bin/sh\nexit 0\n");
    }

    assert.deepEqual(await call(runCommandOutcome, [command], root, 1000), { _tag: "Success" });
  });
});

test("run_command_outcome_times_out_cross_platform", async () => {
  await withTempDir(async (root) => {
    const startedAt = performance.now();
    const outcome = await call(runCommandOutcome, ["bun", "-e", "setInterval(() => {}, 1000)"], root, 100);
    const elapsed = performance.now() - startedAt;

    assert.deepEqual(outcome, { _tag: "TimedOut" });
    assert.equal(elapsed < 1000, true);
  });
});

test("run_install_force_kills_term_trapping_process", async () => {
  if (!isPosix()) return;

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

    const result = spawnSync("bun", [helper], {
      cwd: SYNC_ROOT,
      encoding: "utf8",
      stdio: "pipe",
      timeout: 5000,
      env: {
        ...process.env,
        PATH: process.env.PATH ?? "",
      },
    });

    assert.equal(result.error, undefined, result.stderr || result.stdout);
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(result.stdout.trim(), "false");
  });
});

test("main_reports_lock_contention_and_skips", async () => {
  if (!isPosix()) return;

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

    const result = spawnSync("bun", [helper], {
      cwd: SYNC_ROOT,
      encoding: "utf8",
      stdio: "pipe",
      env: {
        ...process.env,
        HOME: root,
        PATH: process.env.PATH ?? "",
      },
    });

    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(result.stdout.trim(), "0");
    assert.equal(result.stderr.includes("another sync is already running; skipping"), true);
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

    const result = spawnSync("bun", [helper], {
      cwd: SYNC_ROOT,
      encoding: "utf8",
      stdio: "pipe",
      timeout: 5_000,
      env: {
        ...process.env,
        PATH: process.env.PATH ?? "",
      },
    });

    assert.equal(result.status, 124, result.stderr || result.stdout);
    assert.equal(result.stderr.includes("timed out after 1s"), true);
  });
});

test("parse_timeout_seconds_uses_default_for_invalid_values", async () => {
  assert.equal(await call<number>(parseTimeoutSeconds, undefined, 7), 7);
  assert.equal(await call<number>(parseTimeoutSeconds, "0", 7), 7);
  assert.equal(await call<number>(parseTimeoutSeconds, "nope", 7), 7);
  assert.equal(await call<number>(parseTimeoutSeconds, "9", 7), 9);
});

test("sync_env_harness_lookup_is_typed", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);

    const pi = syncEnv.harness(enumMember(HarnessId, "Pi"));
    assert.ok(pi);
    assert.equal(
      harnessSourceRoot(pi!, syncEnv.toolsHome),
      join(root, ".config", "agents", "tools", "pi", "agent"),
    );
    assert.equal(harnessInstructionTarget(pi!), join(root, ".pi", "agent", "AGENTS.md"));

    const claude = syncEnv.harness(enumMember(HarnessId, "Claude"));
    assert.ok(claude);
    assert.equal(harnessInstructionTarget(claude!), join(root, ".claude", "CLAUDE.md"));
  });
});

test("sync_plan_resolves_hook_targets_from_harness_specs", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const syncPlan = await call<{
      hooks: Record<string, unknown>[];
    }>(buildSyncPlan, syncEnv);

    const packageHook = syncPlan.hooks.find((hook) => hook.kind === "PackageBootstrap");
    const extensionHook = syncPlan.hooks.find((hook) => hook.kind === "ExtensionDeps");

    assert.ok(packageHook);
    assert.equal(
      packageHook!.manifestPath,
      join(root, ".config", "agents", "tools", "pi", "agent", "packages.json"),
    );
    assert.equal(
      packageHook!.runtimeSettingsPath,
      join(root, ".pi", "agent", "settings.json"),
    );
    assert.equal(
      packageHook!.cacheRoot,
      join(root, ".local", "share", "agents", "pi-packages"),
    );

    assert.ok(extensionHook);
    assert.equal(
      extensionHook!.root,
      join(root, ".pi", "agent", "extensions"),
    );
  });
});

test("run_sync_happy_path", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);

    writeFile(join(root, ".config", "agents", "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(root, ".config", "agents", "assets", "mcporter.jsonc"), '{"x":1}');
    writeFile(join(root, ".config", "agents", "assets", "skills", "skill.txt"), "skill-content");
    writeFile(join(root, ".config", "agents", "tools", "codex", "config.toml"), "codex = true");
    writeFile(
      join(root, ".config", "agents", "tools", "omp", "agent", "config.yml"),
      "theme:\n  dark: graphite\n",
    );
    writeFile(
      join(root, ".config", "agents", "tools", "pi", "agent", "extensions", "answer", "package.json"),
      "{}",
    );
    mkdirSync(join(root, ".config", "agents", "tools", "pi", "agent", "extensions", "answer", "node_modules"), {
      recursive: true,
    });
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "stale.ts"), "stale");
    writeFile(join(root, ".omp", "agent", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".omp", "agent", "logs", "keep.txt"), "keep-me");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(exists(join(root, ".codex", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".claude", "CLAUDE.md")), true);
    assert.equal(exists(join(root, ".claude", "AGENTS.md")), false);
    assert.equal(exists(join(root, ".config", "opencode", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".pi", "agent", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".omp", "agent", "AGENTS.md")), true);
    assert.equal(exists(join(root, ".omp", "agent", "config.yml")), true);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".mcporter", "mcporter.json")), true);
    assert.equal(exists(join(root, ".pi", "agent", "auth.json")), true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "stale.ts")), false);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "stale.txt")), false);
    assert.equal(exists(join(root, ".omp", "agent", "logs", "keep.txt")), true);
  });
});

test("run_sync_missing_sources_is_non_fatal", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    assert.equal(await call<boolean>(runSync, syncEnv), true);
  });
});

test("run_sync_claude_uses_claude_md", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const sourceAgentFile = join(root, ".config", "agents", "assets", "AGENTS.md");
    writeFile(sourceAgentFile, "agent-instructions");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(readText(join(root, ".claude", "CLAUDE.md")), "agent-instructions");
    assert.equal(exists(join(root, ".claude", "AGENTS.md")), false);
    assert.equal(readText(sourceAgentFile), "agent-instructions");
  });
});

test("run_sync_cleans_managed_entries_for_multiple_harnesses", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "assets", "skills", "skill.txt"), "fresh-skill");
    writeFile(join(agentsRoot, "tools", "codex", "config.toml"), "fresh = true\n");
    writeFile(join(agentsRoot, "tools", "omp", "agent", "config.yml"), "theme:\n  light: graphite\n");

    writeFile(join(root, ".codex", "config.toml"), "stale = true\n");
    writeFile(join(root, ".codex", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".codex", "logs", "keep.txt"), "keep-me");
    writeFile(join(root, ".omp", "agent", "config.yml"), "stale-config\n");
    writeFile(join(root, ".omp", "agent", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".omp", "agent", "logs", "keep.txt"), "keep-me");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(readText(join(root, ".codex", "config.toml")), "fresh = true\n");
    assert.equal(readText(join(root, ".omp", "agent", "config.yml")), "theme:\n  light: graphite\n");
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

    writeFile(join(agentsRoot, "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "assets", "skills", "skill.txt"), "fresh-skill");
    writeFile(join(agentsRoot, "tools", "omp", "agent", "config.yml"), "theme:\n  light: graphite\n");

    writeFile(join(root, ".omp", "agent", "config.yml"), "stale-config\n");
    writeFile(join(root, ".omp", "agent", "skills", "stale.txt"), "stale-skill");
    writeFile(join(root, ".omp", "agent", "logs", "keep.txt"), "keep-me");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(readText(join(root, ".omp", "agent", "config.yml")), "theme:\n  light: graphite\n");
    assert.equal(exists(join(root, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".omp", "agent", "skills", "stale.txt")), false);
    assert.equal(exists(join(root, ".omp", "agent", "logs", "keep.txt")), true);
  });
});

test("run_sync_cleans_legacy_pi_entries_without_prior_state", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(root, ".pi", "agent", "legacy", "old.txt"), "stale");
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(exists(join(root, ".pi", "agent", "legacy")), false);
    assert.equal(exists(join(root, ".pi", "agent", "auth.json")), true);
  });
});

test("run_sync_removes_entries_removed_from_ssot_after_prior_sync", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");
    const codexConfig = join(agentsRoot, "tools", "codex", "config.toml");
    const skillsRoot = join(agentsRoot, "assets", "skills");

    writeFile(join(agentsRoot, "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(skillsRoot, "skill.txt"), "fresh-skill");
    writeFile(codexConfig, "fresh = true\n");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(exists(join(root, ".codex", "config.toml")), true);
    assert.equal(exists(join(root, ".codex", "skills", "skill.txt")), true);
    assert.equal(exists(join(root, ".local", "share", "agents", "sync-managed", "codex.json")), true);

    rmSync(codexConfig, { force: true });
    rmSync(skillsRoot, { recursive: true, force: true });
    writeFile(join(root, ".codex", "logs", "keep.txt"), "keep-me");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(exists(join(root, ".codex", "config.toml")), false);
    assert.equal(exists(join(root, ".codex", "skills")), false);
    assert.equal(exists(join(root, ".codex", "logs", "keep.txt")), true);
  });
});

test("run_sync_preserves_generated_extension_runtime_when_hook_inputs_match", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const { fingerprintTree } = await import("@core/hook-state.ts");

    writeFile(join(root, ".config", "agents", "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(root, ".config", "agents", "tools", "pi", "agent", "extensions", "context", "index.ts"), "export const live = true;\n");
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js"), "module.exports = 1;\n");
    writeFile(
      join(root, ".local", "share", "agents", "sync-managed", "pi.extension-deps.json"),
      `${JSON.stringify(
        {
          fingerprint: fingerprintTree(join(root, ".config", "agents", "tools", "pi", "agent", "extensions")),
          generatedEntries: ["package.json", "node_modules"],
        },
        null,
        2,
      )}\n`,
    );

    const success = await call<boolean>(runSync, syncEnv);
    assert.equal(success, true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package.json")), true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js")), true);
  });
});

test("run_sync_drops_legacy_npm_extension_state_entries_without_reinstall", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const { fingerprintTree } = await import("@core/hook-state.ts");
    const sourceRoot = join(root, ".config", "agents", "tools", "pi", "agent", "extensions");
    const statePath = join(root, ".local", "share", "agents", "sync-managed", "pi.extension-deps.json");

    writeFile(join(root, ".config", "agents", "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(sourceRoot, "context", "index.ts"), "export const live = true;\n");
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js"), "module.exports = 1;\n");
    writeFile(join(root, ".pi", "agent", "extensions", "package-lock.json"), '{"lockfileVersion":3}\n');
    writeFile(join(root, ".pi", "agent", "extensions", "npm-shrinkwrap.json"), '{"lockfileVersion":3}\n');
    writeFile(
      statePath,
      `${JSON.stringify(
        {
          fingerprint: fingerprintTree(sourceRoot),
          generatedEntries: ["package.json", "node_modules", "package-lock.json", "npm-shrinkwrap.json"],
        },
        null,
        2,
      )}\n`,
    );

    const success = await call<boolean>(runSync, syncEnv);
    assert.equal(success, true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package.json")), true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js")), true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package-lock.json")), false);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "npm-shrinkwrap.json")), false);

    const state = JSON.parse(readText(statePath)) as { generatedEntries?: unknown };
    assert.deepEqual(state.generatedEntries, ["package.json", "node_modules"]);
  });
});

test("run_sync_removes_generated_extension_runtime_when_hook_inputs_change", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);

    writeFile(join(root, ".config", "agents", "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(root, ".config", "agents", "tools", "pi", "agent", "extensions", "context", "index.ts"), "export const live = true;\n");
    writeFile(join(root, ".pi", "agent", "auth.json"), '{"token":1}');
    writeFile(join(root, ".pi", "agent", "extensions", "package.json"), '{"name":"generated"}\n');
    writeFile(join(root, ".pi", "agent", "extensions", "node_modules", "dep", "index.js"), "module.exports = 1;\n");
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

    const success = await call<boolean>(runSync, syncEnv);
    assert.equal(success, true);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "package.json")), false);
    assert.equal(exists(join(root, ".pi", "agent", "extensions", "node_modules")), false);
  });
});

test("run_sync_omp_does_not_bootstrap_packages", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const agentsRoot = join(root, ".config", "agents");

    writeFile(join(agentsRoot, "assets", "AGENTS.md"), "agent-instructions");
    writeFile(join(agentsRoot, "tools", "omp", "agent", "config.yml"), "interruptMode: immediate\n");
    writeFile(join(agentsRoot, "tools", "omp", "agent", "packages.json"), "this is not valid json\n");

    assert.equal(await call<boolean>(runSync, syncEnv), true);
    assert.equal(readText(join(root, ".omp", "agent", "packages.json")), "this is not valid json\n");
    assert.equal(exists(join(root, ".omp", "agent", "config.yml")), true);
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

    const manifest = await call<{ packages: string[] }>(readPackageManifest, path);
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

    await call<void>(patchRuntimeSettings, path, [join(root, "pkg")]);
    const settings = JSON.parse(readText(path)) as { theme?: string; packages?: string[] };
    assert.equal(settings.theme, "dark");
    assert.deepEqual(settings.packages, [join(root, "pkg")]);
  });
});

test("package_cache_dir_is_stable", async () => {
  const root = "/tmp/cache-root";
  const left = await call<string>(packageCacheDir, root, "https://github.com/tintinweb/pi-supervisor");
  const right = await call<string>(packageCacheDir, root, "https://github.com/tintinweb/pi-supervisor");
  assert.equal(left, right);
});

test("package_cache_dir_uses_basename_for_local_paths", async () => {
  const root = "/tmp/cache-root";
  const sources = [
    "packages\\foo",
    ".\\packages\\foo",
    "C:\\x\\foo",
    "\\\\server\\share\\foo",
  ];

  for (const source of sources) {
    const cacheDir = await call<string>(packageCacheDir, root, source);
    assert.equal(basename(cacheDir).startsWith("foo-"), true, source);
  }
});

test("github_clone_command_prefers_gh_when_available", async () => {
  await withTempDir(async (root) => {
    const target = join(root, "out");
    const command = await call<string[]>(commandForTests, "https://github.com/tintinweb/pi-supervisor", target);
    assert.equal(command[0], "gh");
    assert.equal(
      await call<string | null>(githubSlugForTests, "https://github.com/tintinweb/pi-supervisor"),
      "tintinweb/pi-supervisor",
    );
  });
});

test("github_clone_falls_back_to_git_after_gh_failure", async () => {
  await withTempDir(async (root) => {
    const target = join(root, "out");
    const [success, attempts] = await call<[boolean, string[][]]>(
      cloneAttemptsForTests,
      "https://github.com/tintinweb/pi-supervisor",
      target,
      true,
      [false, true],
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
    assert.equal(await call<boolean>(validatePackageForTests, manifestPkg), true);

    const conventionalPkg = join(root, "conventional-pkg");
    writeFile(join(conventionalPkg, "extensions", "index.ts"), "export default {}\n");
    assert.equal(await call<boolean>(validatePackageForTests, conventionalPkg), true);
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
    assert.equal(await call<boolean>(validatePackageForTests, pkg), false);

    writeFile(join(pkg, "node_modules", "@earendil-works", "pi-tui", "package.json"), "{}\n");
    assert.equal(await call<boolean>(validatePackageForTests, pkg), true);
  });
});

test("validate_package_dir_rejects_malformed_package_json", async () => {
  await withTempDir(async (root) => {
    const pkg = join(root, "bad-pkg");
    writeFile(join(pkg, "package.json"), "{not valid json");

    await assert.rejects(call<boolean>(validatePackageForTests, pkg));
    await assert.rejects(call<boolean>(packageHasBuildScript, pkg));
  });
});

test("run_sync_bootstraps_packages_and_patches_runtime_settings", async () => {
  if (!isPosix()) return;

  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    writeFile(join(root, ".config", "agents", "assets", "AGENTS.md"), "agent-instructions");
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
      join(root, ".config", "agents", "tools", "pi", "agent", "packages.json"),
      `{
  "packages": [
    "${sourceRepo}",
    "${buildRepo}"
  ]
}
`,
    );

    const success = await call<boolean>(runSync, syncEnv);
    assert.equal(success, true);
    const settings = readText(join(root, ".pi", "agent", "settings.json"));
    assert.equal(settings.includes("source-pkg"), true);
    assert.equal(settings.includes("build-pkg"), true);
    assert.equal(
      exists(join(root, ".local", "share", "agents", "pi-packages")),
      true,
    );
  });
});

test("managed_state_helpers_match_safe_entry_rules", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const harness = syncEnv.harness(enumMember(HarnessId, "Codex"));
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

    const names = await call<string[]>(
      loadRecordedEntryNames,
      join(root, ".local", "share", "agents", "sync-managed", "codex.json"),
    );
    assert.deepEqual(names, ["good.txt"]);

    const plan = await call<{ harnesses: { cleanupPaths: string[] }[] }>(planManagedEntries, syncEnv);
    assert.ok(plan.harnesses.length > 0);
  });
});

test("managed_state_write_persists_expected_json", async () => {
  await withTempDir(async (root) => {
    const path = join(root, "state", "codex.json");
    await call<void>(writeRecordedEntryNames, path, ["alpha", "beta"]);
    assert.equal(readText(path), '[\n  "alpha",\n  "beta"\n]\n');
  });
});

test("managed_state_malformed_json_is_recoverable", async () => {
  await withTempDir(async (root) => {
    const syncEnv = makeSyncEnv(root);
    const statePath = join(root, ".local", "share", "agents", "sync-managed", "codex.json");
    writeFile(statePath, "{not valid json");

    const recovered = await call<string[]>(loadRecordedEntryNames, statePath);
    assert.deepEqual(recovered, []);

    const plan = await call<{ harnesses: { cleanupPaths: string[] }[] }>(planManagedEntries, syncEnv);
    assert.ok(plan.harnesses.length > 0);
  });
});

}

function makeSyncEnv(root: string): any {
  const value = SyncEnv as any;
  if (typeof value?.fromHome === "function") {
    return value.fromHome(root, 1_000);
  }
  if (typeof value?.from_home === "function") {
    return value.from_home(root, 1_000);
  }
  if (typeof value === "function") {
    return new value(root, 1_000);
  }
  throw new Error("missing SyncEnv factory");
}

function enumMember(value: unknown, name: string): unknown {
  if (value && typeof value === "object" && name in value) {
    return (value as Record<string, unknown>)[name];
  }
  return name;
}
