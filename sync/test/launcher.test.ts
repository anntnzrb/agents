import { afterEach, beforeEach, type Mock, spyOn, test } from "bun:test";
import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { SyncEnv } from "@core/harness.ts";
import {
  type LauncherProcessResult,
  type LauncherRuntime,
  launchHarness,
  launchNpmPackage,
  npmCacheLayout,
  prepareNpmPackage,
} from "@core/launcher.ts";
import { toolLauncher } from "@core/tool-launchers.ts";

function withTempHome<T>(fn: (home: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "agents-launcher-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

function success(stdout = ""): LauncherProcessResult {
  return { exitCode: 0, stdout, stderr: "", timedOut: false };
}

let errorSpy: Mock<(...args: unknown[]) => void>;
beforeEach(() => {
  errorSpy = spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => errorSpy.mockRestore());

test("npm_launcher_resolves_latest_and_caches_current_previous_without_network", async () => {
  await withTempHome(async (home) => {
    const calls: string[][] = [];
    const runtime: LauncherRuntime = {
      resolveVersion: async () => "1.2.3",
      run: async (command, _options): Promise<LauncherProcessResult> => {
        calls.push([...command]);
        if (command[0] === "npm") {
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "demo");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "demo-package", "1.2.3");
        }
        return success();
      },
    };

    const prepared = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1000 },
    );
    assert.equal(prepared.resolvedVersion, "1.2.3");
    assert.equal(existsSync(prepared.currentBin), true);
    assert.equal(
      readlinkSync(prepared.layout.currentLink).endsWith(join("versions", "1.2.3")),
      true,
    );
    assert.equal(
      calls.some((command) => command.includes("demo-package@1.2.3")),
      true,
    );

    const second = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1000 },
    );
    assert.equal(second.currentBin, prepared.currentBin);
    assert.equal(calls.filter((command) => command[0] === "npm").length, 1);
  });
});

test("npm_launcher_rotates_previous_and_falls_back_to_last_known_good", async () => {
  await withTempHome(async (home) => {
    let version = "1.0.0";
    let failInstall = false;
    let failSmoke = false;
    const runtime: LauncherRuntime = {
      resolveVersion: async () => {
        if (version === "offline") {
          throw new Error("network unavailable");
        }
        return version;
      },
      run: async (command, _options): Promise<LauncherProcessResult> => {
        if (command[0] === "npm") {
          if (failInstall) {
            return {
              exitCode: 1,
              stdout: "",
              stderr: "registry unavailable",
              timedOut: false,
            };
          }
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "demo");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "demo-package", version);
        }
        if (failSmoke && command[0]?.endsWith("demo") && command[1] === "--version") {
          return { exitCode: 1, stdout: "", stderr: "smoke failed", timedOut: false };
        }
        return success();
      },
    };
    const options = { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1000 };

    const first = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      options,
    );
    version = "2.0.0";
    const second = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      options,
    );
    const layout = npmCacheLayout(
      home,
      { tool: "demo", package: "demo-package" },
      join(home, "cache"),
    );
    assert.equal(readlinkSync(layout.currentLink).endsWith(join("versions", "2.0.0")), true);
    assert.equal(readlinkSync(layout.previousLink).endsWith(join("versions", "1.0.0")), true);
    assert.equal(existsSync(first.currentBin), true);
    assert.equal(existsSync(second.currentBin), true);

    version = "offline";
    const offline = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      options,
    );
    assert.equal(offline.resolvedVersion, "2.0.0");
    assert.equal(offline.currentBin, second.currentBin);
    assert.equal(readlinkSync(layout.currentLink).endsWith(join("versions", "2.0.0")), true);

    version = "3.0.0";
    failInstall = true;
    const failedInstall = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      options,
    );
    assert.equal(failedInstall.resolvedVersion, "2.0.0");
    assert.equal(failedInstall.currentBin, second.currentBin);

    version = "4.0.0";
    failInstall = false;
    failSmoke = true;
    const failedSmoke = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      options,
    );
    assert.equal(failedSmoke.resolvedVersion, "2.0.0");
    assert.equal(failedSmoke.currentBin, second.currentBin);
  });
});

test("npm_launcher_first_ever_resolution_failure_still_errors", async () => {
  await withTempHome(async (home) => {
    await assert.rejects(
      prepareNpmPackage(
        { tool: "demo", package: "demo-package", bin: "demo" },
        {
          home,
          cacheHome: join(home, "cache"),
          runtime: {
            resolveVersion: async (): Promise<string> => {
              throw new Error("network unavailable");
            },
          },
          timeoutMs: 1000,
        },
      ),
      /network unavailable/,
    );
  });
});

test("npm_launcher_separates_cache_versions_when_a_harness_changes_package", async () => {
  await withTempHome(async (home) => {
    let offline = false;
    let installs = 0;
    const runtime: LauncherRuntime = {
      resolveVersion: async () => {
        if (offline) {
          throw new Error("network unavailable");
        }
        return "1.0.0";
      },
      run: async (command, _options): Promise<LauncherProcessResult> => {
        if (command[0] === "npm") {
          installs += 1;
          const stage = command[3]!;
          const packageSpec = command.at(-1)!;
          const packageName = packageSpec.slice(0, packageSpec.lastIndexOf("@"));
          const executable = join(stage, "node_modules", ".bin", "demo");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, packageName, "1.0.0");
        }
        return success();
      },
    };
    const options = {
      home,
      cacheHome: join(home, "cache"),
      runtime,
      timeoutMs: 1000,
    };

    const first = await prepareNpmPackage(
      { tool: "demo", package: "package-a", bin: "demo" },
      options,
    );
    const second = await prepareNpmPackage(
      { tool: "demo", package: "package-b", bin: "demo" },
      options,
    );
    offline = true;
    const restored = await prepareNpmPackage(
      { tool: "demo", package: "package-a", bin: "demo" },
      options,
    );

    assert.equal(installs, 2);
    assert.notEqual(first.layout.versionsDir, second.layout.versionsDir);
    assert.equal(second.layout.versionsDir.includes("packages"), true);
    assert.equal(existsSync(second.currentBin), true);
    assert.equal(restored.currentBin, first.currentBin);
    assert.equal(restored.resolvedVersion, "1.0.0");
  });
});

test("interactive_harness_launch_is_unbounded_and_keeps_arguments", async () => {
  await withTempHome(async (home) => {
    const calls: Array<{ command: string[]; timeout: number | undefined; stdio: string }> = [];
    const runtime: LauncherRuntime = {
      resolveVersion: async () => "1.0.0",
      run: async (command, options): Promise<LauncherProcessResult> => {
        calls.push({
          command: [...command],
          timeout: options.timeoutMs,
          stdio: options.stdio ?? "pipe",
        });
        if (command[0] === "npm") {
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "codex");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "@openai/codex", "1.0.0");
        }
        return command[0]?.endsWith("codex") && command[1] === "--help"
          ? { exitCode: 7, stdout: "", stderr: "", timedOut: false }
          : success();
      },
    };
    mkdirSync(join(home, ".config", "agents", "harnesses", "codex"), { recursive: true });
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const harness = syncEnv.harnesses.find((candidate) => candidate.sourceName === "codex")!;
    assert.equal(await launchHarness(syncEnv, harness, ["--help", "hello"], runtime), 7);
    const launchCall = calls.at(-1)!;
    assert.deepEqual(launchCall.command.slice(-2), ["--help", "hello"]);
    assert.equal(launchCall.timeout, undefined);
    assert.equal(launchCall.stdio, "inherit");
  });
});

test("harness_launch_merges_root_env_parent_env_and_adapter_env_with_precedence", async () => {
  await withTempHome(async (home) => {
    const proc = Bun.spawnSync(
      [
        process.execPath,
        "-e",
        `import assert from "node:assert/strict";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SyncEnv } from "@core/harness.ts";
import { launchHarness } from "@core/launcher.ts";

const rootKeyOnly = "AGENTS_SYNC_TEST_ROOT_ONLY_VAR";
const parentKeyOverride = "AGENTS_SYNC_TEST_PARENT_OVERRIDE_VAR";
const adapterCollisionKey = "AGENTS_SYNC_TEST_ADAPTER_COLLISION_VAR";
const home = ${JSON.stringify(home)};

const agentsHome = join(home, ".config", "agents");
mkdirSync(join(agentsHome, "harnesses", "codex"), { recursive: true });
writeFileSync(
  join(agentsHome, ".env"),
  [
    \`\${rootKeyOnly}=root_default_val\`,
    \`\${parentKeyOverride}=root_ignored_val\`,
    \`\${adapterCollisionKey}=root_val_overridden_by_adapter\`,
  ].join("\\n"),
  "utf8",
);

let capturedEnv;
const runtime = {
  resolveVersion: async () => "1.0.0",
  run: async (command, options) => {
    capturedEnv = options.env;
    if (command[0] === "npm") {
      const stage = command[3];
      const executable = join(stage, "node_modules", ".bin", "codex");
      mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
      writeFileSync(executable, "#!/bin/sh\\nexit 0\\n", "utf8");
      chmodSync(executable, 0o755);
      const pkgDir = join(stage, "node_modules", "@openai", "codex");
      mkdirSync(pkgDir, { recursive: true });
      writeFileSync(join(pkgDir, "package.json"), JSON.stringify({ name: "@openai/codex", version: "1.0.0" }) + "\\n");
    }
    return { exitCode: 0, stdout: "", stderr: "", timedOut: false };
  },
};

const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
const baseHarness = syncEnv.harnesses.find((candidate) => candidate.sourceName === "codex");
const harnessWithAdapterEnv = {
  ...baseHarness,
  launcher: {
    ...baseHarness.launcher,
    env: {
      [adapterCollisionKey]: "adapter_wins",
    },
  },
};

await launchHarness(syncEnv, harnessWithAdapterEnv, [], runtime);

assert(capturedEnv !== undefined);
assert.equal(capturedEnv[rootKeyOnly], "root_default_val");
assert.equal(capturedEnv[parentKeyOverride], undefined);
assert.equal(capturedEnv[adapterCollisionKey], "adapter_wins");`,
      ],
      {
        cwd: resolve(import.meta.dir, ".."),
        env: {
          ...Bun.env,
          HOME: home,
          AGENTS_SYNC_TEST_PARENT_OVERRIDE_VAR: "parent_value",
        },
      },
    );
    assert.equal(proc.exitCode, 0);
  });
});

function writePackageManifest(root: string, packageName: string, version: string): void {
  const packageDir = join(root, "node_modules", ...packageName.split("/"));
  mkdirSync(packageDir, { recursive: true });
  writeFileSync(
    join(packageDir, "package.json"),
    `${JSON.stringify({ name: packageName, version })}\n`,
    "utf8",
  );
}

test("tool_launcher_launch_uses_the_registered_npm_spec", async () => {
  await withTempHome(async (home) => {
    const tool = toolLauncher("mcporter")!;
    const calls: Array<{ command: string[]; timeout: number | undefined; stdio: string }> = [];
    const runtime: LauncherRuntime = {
      resolveVersion: async () => "1.0.0",
      run: async (command, options): Promise<LauncherProcessResult> => {
        calls.push({
          command: [...command],
          timeout: options.timeoutMs,
          stdio: options.stdio ?? "pipe",
        });
        if (command[0] === "npm") {
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "mcporter");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "mcporter", "1.0.0");
        }
        return command[0]?.endsWith("mcporter") && command[1] === "list"
          ? { exitCode: 3, stdout: "", stderr: "", timedOut: false }
          : success();
      },
    };
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    assert.equal(tool.package, "mcporter");
    assert.equal(tool.bin, "mcporter");
    assert.equal(
      await launchNpmPackage(
        syncEnv,
        { tool: tool.id, package: tool.package, bin: tool.bin },
        ["list"],
        runtime,
      ),
      3,
    );
    const launchCall = calls.at(-1)!;
    assert.deepEqual(launchCall.command.slice(-1), ["list"]);
    assert.equal(launchCall.timeout, undefined);
    assert.equal(launchCall.stdio, "inherit");
    assert.equal(
      calls.some((entry) => entry.command[0] === "npm" && entry.command.includes("mcporter@1.0.0")),
      true,
    );

    const summarizeTool = toolLauncher("summarize")!;
    assert.equal(summarizeTool.package, "@steipete/summarize");
    assert.equal(summarizeTool.bin, "summarize");
    assert.deepEqual(summarizeTool.defaultArgs, [
      "--force-summary",
      "--timestamps",
      "--format",
      "md",
      "--retries",
      "2",
      "--metrics",
      "detailed",
    ]);
  });
});

test("tool_launcher_lookup_rejects_unknown_ids", () => {
  assert.equal(toolLauncher("codex"), undefined);
});

test("npm_launcher_rejects_unmanaged_conflict_for_current_and_previous", async () => {
  await withTempHome(async (home) => {
    const layout = npmCacheLayout(
      home,
      { tool: "demo", package: "demo-package" },
      join(home, "cache"),
    );
    mkdirSync(layout.versionsDir, { recursive: true });
    const versionDir = join(layout.versionsDir, "1.0.0");
    mkdirSync(versionDir, { recursive: true });
    const currentTarget = join("versions", "1.0.0");
    symlinkSync(currentTarget, layout.currentLink, "dir");
    writeFileSync(layout.previousLink, "real file");

    const runtime: LauncherRuntime = {
      resolveVersion: async () => "1.2.3",
      run: async (command, _options): Promise<LauncherProcessResult> => {
        if (command[0] === "npm") {
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "demo");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "demo-package", "1.2.3");
        }
        return success();
      },
    };

    await assert.rejects(
      prepareNpmPackage(
        { tool: "demo", package: "demo-package", bin: "demo" },
        { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1000 },
      ),
      /unmanaged conflict/,
    );
  });
});
