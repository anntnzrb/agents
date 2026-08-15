import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  readlinkSync,
  rmSync,
  mkdirSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "bun:test";

import { SyncEnv } from "../src/core/harness.ts";
import {
  executableCommand,
  launchHarness,
  npmCacheLayout,
  npmCommand,
  prepareNpmPackage,
  type LauncherProcessResult,
} from "../src/core/launcher.ts";

function withTempHome<T>(fn: (home: string) => T | Promise<T>): Promise<T> {
  const root = mkdtempSync(join(tmpdir(), "agents-launcher-test-"));
  return Promise.resolve(fn(root)).finally(() => {
    rmSync(root, { recursive: true, force: true });
  });
}

function success(stdout = ""): LauncherProcessResult {
  return { exitCode: 0, stdout, stderr: "" };
}

test("npm_launcher_resolves_latest_and_caches_current_previous_without_network", async () => {
  await withTempHome(async (home) => {
    const calls: string[][] = [];
    const runtime = {
      resolveVersion: async (): Promise<string> => "1.2.3",
      run: async (
        command: readonly string[],
        _cwd: string | undefined,
        _timeoutMs: number | undefined,
        _stdio: "pipe" | "inherit",
      ): Promise<LauncherProcessResult> => {
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
      { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1_000 },
    );
    assert.equal(prepared.resolvedVersion, "1.2.3");
    assert.equal(existsSync(prepared.currentBin), true);
    assert.equal(
      readlinkSync(prepared.layout.currentLink).endsWith(join("versions", "1.2.3")),
      true,
    );
    assert.equal(calls.some((command) => command.includes("demo-package@1.2.3")), true);

    const second = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1_000 },
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
    const runtime = {
      resolveVersion: async (): Promise<string> => {
        if (version === "offline") {
          throw new Error("network unavailable");
        }
        return version;
      },
      run: async (
        command: readonly string[],
        _cwd: string | undefined,
        _timeoutMs: number | undefined,
        _stdio: "pipe" | "inherit",
      ): Promise<LauncherProcessResult> => {
        if (command[0] === "npm") {
          if (failInstall) {
            return { exitCode: 1, stdout: "", stderr: "registry unavailable" };
          }
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "demo");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "demo-package", version);
        }
        if (failSmoke && command[0]?.endsWith("demo") && command[1] === "--version") {
          return { exitCode: 1, stdout: "", stderr: "smoke failed" };
        }
        return success();
      },
    };
    const options = { home, cacheHome: join(home, "cache"), runtime, timeoutMs: 1_000 };

    const first = await prepareNpmPackage({ tool: "demo", package: "demo-package", bin: "demo" }, options);
    version = "2.0.0";
    const second = await prepareNpmPackage({ tool: "demo", package: "demo-package", bin: "demo" }, options);
    const layout = npmCacheLayout(
      home,
      { tool: "demo", package: "demo-package" },
      join(home, "cache"),
    );
    assert.equal(
      readlinkSync(layout.currentLink).endsWith(join("versions", "2.0.0")),
      true,
    );
    assert.equal(
      readlinkSync(layout.previousLink).endsWith(join("versions", "1.0.0")),
      true,
    );
    assert.equal(existsSync(first.currentBin), true);
    assert.equal(existsSync(second.currentBin), true);

    version = "offline";
    const offline = await prepareNpmPackage(
      { tool: "demo", package: "demo-package", bin: "demo" },
      options,
    );
    assert.equal(offline.resolvedVersion, "2.0.0");
    assert.equal(offline.currentBin, second.currentBin);
    assert.equal(
      readlinkSync(layout.currentLink).endsWith(join("versions", "2.0.0")),
      true,
    );

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
          timeoutMs: 1_000,
        },
      ),
      /network unavailable/,
    );
  });
});

test("npm_launcher_separates_cache_versions_when_a_harness_changes_package", async () => {
  await withTempHome(async (home) => {
    let installs = 0;
    let offline = false;
    const runtime = {
      resolveVersion: async (): Promise<string> => {
        if (offline) {
          throw new Error("network unavailable");
        }
        return "1.0.0";
      },
      run: async (
        command: readonly string[],
      ): Promise<LauncherProcessResult> => {
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
      timeoutMs: 1_000,
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
    const runtime = {
      resolveVersion: async (): Promise<string> => "1.0.0",
      run: async (
        command: readonly string[],
        _cwd: string | undefined,
        timeout: number | undefined,
        stdio: "pipe" | "inherit",
      ): Promise<LauncherProcessResult> => {
        calls.push({ command: [...command], timeout, stdio });
        if (command[0] === "npm") {
          const stage = command[3]!;
          const executable = join(stage, "node_modules", ".bin", "codex");
          mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
          writeFileSync(executable, "#!/bin/sh\nexit 0\n", "utf8");
          chmodSync(executable, 0o755);
          writePackageManifest(stage, "@openai/codex", "1.0.0");
        }
        return command[0]?.endsWith("codex") && command[1] === "--help"
          ? { exitCode: 7, stdout: "", stderr: "" }
          : success();
      },
    };
    const syncEnv = SyncEnv.fromHome(home, 1_000, { platform: "linux" });
    const harness = syncEnv.harnesses.find((candidate) => candidate.sourceName === "codex")!;
    assert.equal(await launchHarness(syncEnv, harness, ["--help", "hello"], runtime), 7);
    const launchCall = calls.at(-1)!;
    assert.deepEqual(launchCall.command.slice(-2), ["--help", "hello"]);
    assert.equal(launchCall.timeout, undefined);
    assert.equal(launchCall.stdio, "inherit");
  });
});

test("windows_cmd_bins_and_npm_are_mediated_without_string_interpolation", () => {
  const powershellPrefix = [
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    "$command=$args[0];$commandArgs=@($args | Select-Object -Skip 1);& $command @commandArgs;exit $LASTEXITCODE",
  ];
  assert.deepEqual(
    executableCommand(
      "C:\\Users\\Test User\\bin\\codex.cmd",
      ["--help", "hello world", "%PATH%", "a&b", "a\"b"],
      "win32",
    ),
    [
      ...powershellPrefix,
      "C:\\Users\\Test User\\bin\\codex.cmd",
      "--help",
      "hello world",
      "%PATH%",
      "a&b",
      "a\"b",
    ],
  );
  assert.deepEqual(
    executableCommand("C:\\bin\\codex.exe", ["--version"], "win32"),
    ["C:\\bin\\codex.exe", "--version"],
  );
  assert.deepEqual(npmCommand(["view", "pkg@latest", "version"], "win32"), [
    ...powershellPrefix,
    "npm.cmd",
    "view",
    "pkg@latest",
    "version",
  ]);
});

function writePackageManifest(
  root: string,
  packageName: string,
  version: string,
): void {
  const packageDir = join(root, "node_modules", ...packageName.split("/"));
  mkdirSync(packageDir, { recursive: true });
  writeFileSync(
    join(packageDir, "package.json"),
    `${JSON.stringify({ name: packageName, version })}\n`,
    "utf8",
  );
}
