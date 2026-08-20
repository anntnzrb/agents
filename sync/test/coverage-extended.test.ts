import { beforeEach, describe, expect, spyOn, test } from "bun:test";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join } from "node:path";
import {
  cliProxyModelsUrl,
  cliProxyRichModelsUrl,
  isCliProxyGatewayHost,
  publishCliProxyEndpointTemplates,
  syncCliProxyEndpointTemplate,
} from "@core/cliproxy-deployment.ts";
import { SyncEnv } from "@core/harness.ts";
import {
  clearExtensionHookState,
  fingerprintTree,
  prepareExtensionHookState,
  recordExtensionHookState,
} from "@core/hook-state.ts";
import {
  launchMain,
  parseTimeoutSeconds,
  runSync,
  syncLockPath,
  syncTimeout,
  tryAcquireSyncLock,
} from "@core/index.ts";
import { copyDirInto, copyItem, runJobsWithPreserve } from "@core/jobs.ts";
import { launchNpmPackage, npmCacheLayout, prepareNpmPackage } from "@core/launcher.ts";
import {
  cleanManagedEntries,
  loadRecordedEntryNames,
  planManagedEntries,
  recordManagedEntries,
  writeRecordedEntryNames,
} from "@core/managed-state.ts";
import { isCliProxyRunning, prepareManagedTools } from "@core/managed-tools.ts";
import {
  renderSecretTemplate,
  syncPrivateTextFile,
  syncSecretTemplate,
} from "@core/secret-template.ts";
import {
  reconcileWrapperFiles,
  reconcileWrappers,
  WRAPPER_MARKER,
  wrapperDestinations,
  wrapperDirectory,
} from "@core/wrappers.ts";
import { iterExtensionPackages, runInstall } from "@extensions/install.ts";
import {
  installInferredImportPackages,
  installPackageDeps,
  runPackageBuild,
} from "@packages/process.ts";
import {
  cloneAttemptsForTests,
  commandForTests,
  githubSlugForTests,
  packageCacheDir,
  replaceDirAtomically,
  rmEntry,
  stagingDirFor,
} from "@packages/source.ts";
import {
  missingPackageRoots,
  packageHasBuildScript,
  packageIsHealthy,
} from "@packages/validate.ts";
import { assertNever, err, isErrno, panicMessage, warn } from "@runtime/errors.ts";
import { copyTree, isSymlink, syncManagedChildren, syncManagedTree } from "@runtime/fs.ts";
import { releaseSyncLock, tryAcquireSyncLock as tryAcquireLockImpl } from "@runtime/lock.ts";
import {
  commandExists,
  logCommandFailure,
  pickBunRunner,
  runCommand,
  runCommandOutcome,
} from "@runtime/process.ts";

beforeEach(() => {
  spyOn(console, "error").mockImplementation(() => {});
});

function withTempDir<T>(fn: (dir: string) => T | Promise<T>): Promise<T> {
  const dir = mkdtempSync(join(tmpdir(), "agents-cov-"));
  return Promise.resolve(fn(dir)).finally(() => {
    rmSync(dir, { recursive: true, force: true });
  });
}

describe("runtime/errors.ts", () => {
  test("panicMessage handles strings, errors, and unknowns", () => {
    expect(panicMessage("error string")).toBe("error string");
    expect(panicMessage(new Error("boom"))).toBe("boom");
    expect(panicMessage({ custom: 123 })).toBe("panic");
    expect(panicMessage(undefined)).toBe("panic");
  });

  test("err and warn functions", () => {
    err("test error");
    warn("test warning");
  });

  test("isErrno checks code property", () => {
    expect(isErrno({ code: "ENOENT" }, "ENOENT")).toBe(true);
    expect(isErrno({ code: "EEXIST" }, "ENOENT")).toBe(false);
    expect(isErrno(null, "ENOENT")).toBe(false);
    expect(isErrno("not object", "ENOENT")).toBe(false);
  });

  test("assertNever throws", () => {
    expect(() => assertNever("unexpected" as never)).toThrow("unhandled variant");
  });
});

describe("runtime/process.ts & packages/process.ts", () => {
  test("commandExists and pickBunRunner", async () => {
    expect(await commandExists("bun")).toBe(true);
    expect(await commandExists("non_existent_binary_xyz_123")).toBe(false);
    expect(await pickBunRunner()).toBe("bun");
  });

  test("runCommandOutcome missing command and execution", async () => {
    expect(await runCommandOutcome([], undefined, 1000)).toEqual({ _tag: "MissingCommand" });
    expect(await runCommandOutcome(["non_existent_binary_xyz_123"], undefined, 1000)).toEqual({
      _tag: "MissingCommand",
    });

    const success = await runCommandOutcome(["echo", "hello"], undefined, 5000);
    expect(success._tag).toBe("Success");

    const failed = await runCommandOutcome(["bun", "-e", "process.exit(1)"], undefined, 5000);
    expect(failed._tag).toBe("Failure");

    const timedOut = await runCommandOutcome(
      ["bun", "-e", "await new Promise(() => {})"],
      undefined,
      50,
    );
    expect(timedOut._tag).toBe("TimedOut");
  });

  test("runCommand and logCommandFailure", async () => {
    expect(await runCommand(["echo", "hi"], undefined, 5000, "echo")).toBe(true);
    expect(await runCommand(["non_existent_bin_123"], undefined, 1000, "test")).toBe(false);

    logCommandFailure(["cmd"], "action", { _tag: "Success" });
    logCommandFailure(["cmd"], "action", { _tag: "MissingCommand" });
    logCommandFailure(["cmd"], "action", { _tag: "Failure", detail: "bad" });
    logCommandFailure(["cmd"], "action", { _tag: "TimedOut" });
  });

  test("installPackageDeps, installInferredImportPackages, runPackageBuild", async () => {
    await withTempDir(async (dir) => {
      // Without package.json
      expect(await installPackageDeps(dir, 5000)).toBe(true);

      // With valid package.json but no missing imports
      writeFileSync(join(dir, "package.json"), '{"name":"test","private":true}\n');
      expect(await installPackageDeps(dir, 10000)).toBe(true);

      // With build script
      writeFileSync(
        join(dir, "package.json"),
        '{"name":"test","private":true,"scripts":{"build":"echo building"}}\n',
      );
      expect(await runPackageBuild(dir, 10000)).toBe(true);

      // Inferred import packages when missing imports
      writeFileSync(join(dir, "index.ts"), 'import "lodash";\n');
      const subDir = join(dir, "subpkg");
      mkdirSync(subDir, { recursive: true });
      writeFileSync(join(subDir, "main.ts"), 'import "chalk";\n');
      expect(await installInferredImportPackages(subDir, 10000, subDir)).toBe(true);
    });
  });
});

describe("runtime/lock.ts", () => {
  test("tryAcquireSyncLock and releaseSyncLock", async () => {
    await withTempDir(async (dir) => {
      const lockPath = join(dir, "test.lock");
      const lock1 = tryAcquireLockImpl(dir, lockPath);
      expect(lock1).toBeDefined();

      // Second acquire should detect lock collision and return undefined
      const lock2 = tryAcquireLockImpl(dir, lockPath);
      expect(lock2).toBeUndefined();

      if (lock1) {
        releaseSyncLock(lock1);
      }

      // Re-acquiring after release should succeed
      const lock3 = tryAcquireLockImpl(dir, lockPath);
      expect(lock3).toBeDefined();
      if (lock3) {
        releaseSyncLock(lock3);
      }
    });
  });
});

describe("runtime/fs.ts", () => {
  test("rmEntry, copyTree, syncManagedTree, syncManagedChildren", async () => {
    await withTempDir(async (dir) => {
      const srcDir = join(dir, "src");
      const dstDir = join(dir, "dst");
      mkdirSync(srcDir, { recursive: true });
      writeFileSync(join(srcDir, "file1.txt"), "hello");
      mkdirSync(join(srcDir, "sub"), { recursive: true });
      writeFileSync(join(srcDir, "sub", "file2.txt"), "world");

      copyTree(srcDir, dstDir);
      expect(existsSync(join(dstDir, "file1.txt"))).toBe(true);
      expect(existsSync(join(dstDir, "sub", "file2.txt"))).toBe(true);

      // Copy single file
      const singleDst = join(dir, "single.txt");
      copyTree(join(srcDir, "file1.txt"), singleDst);
      expect(readFileSync(singleDst, "utf8")).toBe("hello");

      // syncManagedTree
      const managedDst = join(dir, "managed");
      syncManagedTree(srcDir, managedDst, ["preserved.txt"]);
      expect(existsSync(join(managedDst, "file1.txt"))).toBe(true);

      // syncManagedChildren
      const childrenDst = join(dir, "children");
      syncManagedChildren(srcDir, childrenDst);
      expect(existsSync(join(childrenDst, "file1.txt"))).toBe(true);

      // rmEntry on symlink, file, directory, and non-existent
      symlinkSync(join(srcDir, "file1.txt"), join(srcDir, "link1"));
      expect(isSymlink(join(srcDir, "link1"))).toBe(true);
      expect(isSymlink(join(srcDir, "file1.txt"))).toBe(false);

      rmEntry(join(srcDir, "link1"));
      expect(existsSync(join(srcDir, "link1"))).toBe(false);
      rmEntry(join(srcDir, "file1.txt"));
      expect(existsSync(join(srcDir, "file1.txt"))).toBe(false);
      rmEntry(srcDir);
      expect(existsSync(srcDir)).toBe(false);
      rmEntry(join(dir, "never_existed"));
    });
  });
});

describe("packages/source.ts & packages/validate.ts", () => {
  test("packageCacheDir, stagingDirFor, replaceDirAtomically", async () => {
    await withTempDir(async (dir) => {
      const cacheDir = packageCacheDir(dir, "https://github.com/foo/bar.git");
      expect(cacheDir.includes("bar-")).toBe(true);

      const localCacheDir = packageCacheDir(dir, "/tmp/my-local-package/");
      expect(localCacheDir.includes("my-local-package-")).toBe(true);

      const staging = stagingDirFor(join(dir, "final"));
      expect(staging.includes("staging-")).toBe(true);

      // Atomic replace
      const src = join(dir, "stage-src");
      const dst = join(dir, "final-dst");
      mkdirSync(src, { recursive: true });
      writeFileSync(join(src, "pkg.json"), "{}");
      await replaceDirAtomically(src, dst);
      expect(existsSync(join(dst, "pkg.json"))).toBe(true);
    });
  });

  test("clonePackage, githubSlugForTests, commandForTests, cloneAttemptsForTests", async () => {
    expect(githubSlugForTests("https://github.com/owner/repo.git")).toBe("owner/repo");
    expect(githubSlugForTests("git@github.com:owner/repo.git")).toBe("owner/repo");
    expect(githubSlugForTests("https://gitlab.com/owner/repo.git")).toBeNull();

    const cmd = commandForTests("https://github.com/owner/repo", "/tmp/target");
    expect(cmd[0]).toBe("gh");

    const [success, attempts] = await cloneAttemptsForTests(
      "https://github.com/owner/repo",
      "/tmp/target",
      true,
      [false, true],
    );
    expect(success).toBe(true);
    expect(attempts.length).toBe(2);
  });

  test("package validation and missing roots", async () => {
    await withTempDir(async (dir) => {
      expect(packageIsHealthy(dir)).toBe(false);
      expect(packageHasBuildScript(dir)).toBe(false);
      expect(missingPackageRoots(dir)).toEqual([]);

      mkdirSync(join(dir, "skills"), { recursive: true });
      writeFileSync(join(dir, "skills", "my-skill.txt"), "content");
      expect(packageIsHealthy(dir)).toBe(true);
    });
  });
});

describe("core/hook-state.ts", () => {
  test("fingerprintTree, prepareExtensionHookState, recordExtensionHookState, clearExtensionHookState", async () => {
    await withTempDir(async (dir) => {
      const root = join(dir, "source");
      mkdirSync(root, { recursive: true });
      writeFileSync(join(root, "file.ts"), "const x = 1;");
      mkdirSync(join(root, "sub"), { recursive: true });
      writeFileSync(join(root, "sub", "file2.ts"), "const y = 2;");

      const fp1 = fingerprintTree(root);
      expect(fp1).toBeDefined();

      const statePath = join(dir, "hook-state.json");
      const syncEnv = SyncEnv.fromHome(dir, 1000);
      const hookPlan = {
        kind: "ExtensionDeps" as const,
        harness: syncEnv.harnesses[0]!,
        root: dir,
        sourceRoot: root,
        statePath,
        jobRoot: dir,
        relativeRoot: "",
        timeoutMs: 1000,
      };

      const prepared = prepareExtensionHookState(hookPlan);
      expect(prepared.fingerprint).toBe(fp1);

      recordExtensionHookState(hookPlan, prepared);
      expect(existsSync(statePath)).toBe(true);

      clearExtensionHookState(statePath);
      expect(existsSync(statePath)).toBe(false);
    });
  });
});

describe("extensions/install.ts", () => {
  test("iterExtensionPackages and runInstall", async () => {
    await withTempDir(async (dir) => {
      const pkgDir = join(dir, "ext1");
      mkdirSync(pkgDir, { recursive: true });
      writeFileSync(join(pkgDir, "package.json"), "{}");

      const pkgs = await iterExtensionPackages(dir);
      expect(pkgs).toContain(pkgDir);

      expect(await runInstall(["echo", "installed"], pkgDir, 5000)).toBe(true);
    });
  });
});

describe("core/secret-template.ts", () => {
  test("renderSecretTemplate, syncSecretTemplate, syncPrivateTextFile", async () => {
    await withTempDir(async (dir) => {
      const template = ["API_KEY=$", "{SECRET_KEY}\nURL=$", "{API_URL}\n"].join("");
      const secrets = { SECRET_KEY: "secret123", API_URL: "https://example.com" };
      const rendered = renderSecretTemplate(template, secrets);
      expect(rendered.includes('"secret123"')).toBe(true);

      expect(() => renderSecretTemplate(["$", "{INVALID-KEY}"].join(""), {})).toThrow(
        "invalid secret placeholder",
      );
      expect(() => renderSecretTemplate(["$", "{MISSING_KEY}"].join(""), {})).toThrow(
        "missing secret",
      );

      const tmplPath = join(dir, "template.env");
      const secPath = join(dir, "secrets.json");
      const dstPath = join(dir, "out.env");
      writeFileSync(tmplPath, template);
      writeFileSync(secPath, JSON.stringify(secrets));

      syncSecretTemplate(tmplPath, dstPath, secPath);
      expect(readFileSync(dstPath, "utf8")).toBe(rendered);

      syncPrivateTextFile(dstPath, rendered); // idempotence
    });
  });
});

describe("core/managed-state.ts", () => {
  test("loadRecordedEntryNames, writeRecordedEntryNames, cleanManagedEntries", async () => {
    await withTempDir(async (dir) => {
      const stateFile = join(dir, "state.json");
      expect(loadRecordedEntryNames(stateFile)).toEqual([]);

      writeRecordedEntryNames(stateFile, ["entry1", "entry2"]);
      expect(loadRecordedEntryNames(stateFile)).toEqual(["entry1", "entry2"]);

      // Unsafe entries filtered
      writeFileSync(stateFile, JSON.stringify(["safe", "../unsafe", "/tmp/escape"]));
      expect(loadRecordedEntryNames(stateFile)).toEqual(["safe"]);

      // Managed sync plan with deployment fixture
      mkdirSync(join(dir, ".config", "agents", "tools", "cliproxyapi"), { recursive: true });
      writeFileSync(
        join(dir, ".config", "agents", "tools", "cliproxyapi", "deployment.json"),
        JSON.stringify({
          server: { hostname: "localhost" },
          listen: { host: "127.0.0.1", port: 9443 },
          client: { baseUrl: "https://127.0.0.1:9443/v1" },
        }),
      );

      const syncEnv = SyncEnv.fromHome(dir, 1000);
      const plan = planManagedEntries(syncEnv);
      expect(cleanManagedEntries(plan)).toBe(true);
      expect(recordManagedEntries(plan)).toBe(true);
    });
  });
});

describe("core/wrappers.ts", () => {
  test("wrapper destinations, rendering, reconciliation", async () => {
    await withTempDir(async (dir) => {
      const syncEnv = SyncEnv.fromHome(dir, 1000);
      const destinations = wrapperDestinations(syncEnv);
      expect(destinations.length).toBeGreaterThan(0);

      expect(wrapperDirectory(syncEnv)).toBe(join(dir, ".local", "bin"));

      const result = reconcileWrapperFiles(syncEnv, destinations);
      expect(result.owned.length).toBe(destinations.length);

      expect(reconcileWrappers(syncEnv)).toBe(true);

      // Reconcile when a stale managed wrapper needs removal
      const staleWrapper = join(dir, ".local", "bin", "stale-tool");
      writeFileSync(staleWrapper, `#!/bin/sh\n# ${WRAPPER_MARKER}\nexit 0\n`);
      const stateFile = join(syncEnv.managedStateHome, "wrappers.json");
      writeFileSync(stateFile, JSON.stringify({ version: 1, entries: [staleWrapper] }));
      const afterStale = reconcileWrapperFiles(syncEnv, destinations);
      expect(afterStale.removed).toContain(staleWrapper);
    });
  });
});

describe("core/managed-tools.ts", () => {
  test("prepareManagedTools and isCliProxyRunning", async () => {
    await withTempDir(async (dir) => {
      const syncEnv = SyncEnv.fromHome(dir, 1000);
      const tools = await prepareManagedTools(syncEnv);
      expect(tools).toEqual([]);

      const running = await isCliProxyRunning(
        {
          server: { hostname: "localhost" },
          listen: { host: "127.0.0.1", port: 9443 },
          client: { baseUrl: "https://127.0.0.1:9443/v1" },
        },
        50,
        async () => {
          throw new Error("offline");
        },
      );
      expect(running).toBe(false);
    });
  });

  test("prepareManagedTools with download and extract", async () => {
    await withTempDir(async (dir) => {
      const cliProxyAssets = join(dir, ".config", "agents", "tools", "cliproxyapi");
      mkdirSync(cliProxyAssets, { recursive: true });
      const archiveContent = "fake archive";
      const checksum = new Bun.CryptoHasher("sha256").update(archiveContent).digest("hex");
      writeFileSync(
        join(cliProxyAssets, "release.json"),
        JSON.stringify({
          repository: "router-for-me/CLIProxyAPI",
          version: "7.2.132",
          binary: "cli-proxy-api",
          assets: {
            "darwin-arm64": {
              name: "CLIProxyAPI.tar.gz",
              sha256: checksum,
            },
          },
        }),
      );

      const syncEnv = SyncEnv.fromHome(dir, 1000, { platform: "darwin" });
      const tools = await prepareManagedTools(syncEnv, {
        arch: "arm64",
        cacheHome: join(dir, "cache"),
        download: async (_url, dest) => {
          writeFileSync(dest, archiveContent);
        },
        extract: async (_archive, dest, binary) => {
          writeFileSync(join(dest, binary), "#!/bin/sh\nexit 0\n");
        },
      });

      expect(tools.length).toBe(1);
      expect(tools[0]!.command).toBe("cli-proxy-api");
    });
  });
});

describe("core/cliproxy-deployment.ts", () => {
  test("urls, gateway host, and endpoint publication", async () => {
    const deployment = {
      server: { hostname: hostname() },
      listen: { host: "127.0.0.1", port: 9443 },
      client: { baseUrl: "https://127.0.0.1:9443/v1" },
    };

    expect(cliProxyModelsUrl(deployment)).toBe("https://127.0.0.1:9443/v1/models");
    expect(cliProxyRichModelsUrl(deployment)).toBe(
      "https://127.0.0.1:9443/v1/models?client_version=0.144.1",
    );
    expect(isCliProxyGatewayHost(deployment)).toBe(true);
    expect(isCliProxyGatewayHost(deployment, "other-host")).toBe(false);

    await withTempDir(async (dir) => {
      const src = join(dir, "template.json");
      const dst = join(dir, "endpoint.json");
      writeFileSync(src, JSON.stringify({ url: ["$", "{CLIPROXY_CLIENT_BASE_URL}"].join("") }));

      syncCliProxyEndpointTemplate(src, dst, deployment);
      expect(readFileSync(dst, "utf8")).toBe('{"url":"https://127.0.0.1:9443/v1"}');

      const pubResult = await publishCliProxyEndpointTemplates([{ src, dst }], deployment, {
        skipReadiness: true,
      });
      expect(pubResult).toBe("published");
    });
  });
});

describe("core/launcher.ts", () => {
  test("npmCacheLayout and launcher operations", async () => {
    await withTempDir(async (dir) => {
      const layout = npmCacheLayout(dir, { tool: "test-tool", package: "test-pkg" });
      expect(layout.toolCache.includes("test-tool")).toBe(true);

      const syncEnv = SyncEnv.fromHome(dir, 1000);
      const result = await launchNpmPackage(
        syncEnv,
        {
          tool: "demo",
          package: "demo-package",
          bin: "demo",
        },
        ["--help"],
        {
          resolveVersion: async () => "1.0.0",
          run: async (cmd) => {
            if (cmd[0] === "npm") {
              const stage = cmd[3]!;
              mkdirSync(join(stage, "node_modules", ".bin"), { recursive: true });
              mkdirSync(join(stage, "node_modules", "demo-package"), { recursive: true });
              const execPath = join(stage, "node_modules", ".bin", "demo");
              writeFileSync(execPath, "#!/bin/sh\nexit 0\n");
              chmodSync(execPath, 0o755);
              writeFileSync(
                join(stage, "node_modules", "demo-package", "package.json"),
                JSON.stringify({ name: "demo-package", version: "1.0.0" }),
              );
            }
            return { exitCode: 0, stdout: "1.0.0", stderr: "" };
          },
        },
      );
      expect(result).toBe(0);
    });
  });

  test("launcher spec validation and error handling", async () => {
    await withTempDir(async (dir) => {
      expect(() => npmCacheLayout(dir, { tool: "invalid/tool", package: "valid-pkg" })).toThrow(
        "invalid tool",
      );
      expect(() => npmCacheLayout(dir, { tool: "", package: "valid-pkg" })).toThrow("invalid tool");

      let caughtError: unknown;
      try {
        await prepareNpmPackage(
          { tool: "demo", package: "invalid!pkg", bin: "demo" },
          { home: dir, timeoutMs: 1000 },
        );
      } catch (error) {
        caughtError = error;
      }
      expect(caughtError).toBeDefined();
      expect(String(caughtError)).toContain("invalid package");
    });
  });
});

describe("core/jobs.ts", () => {
  test("copyItem, copyDirInto, runJobsWithPreserve execution", async () => {
    await withTempDir(async (dir) => {
      const srcFile = join(dir, "src.txt");
      const dstFile = join(dir, "dst.txt");
      writeFileSync(srcFile, "hello job");

      expect(copyItem(srcFile, dstFile)).toBe(true);
      expect(readFileSync(dstFile, "utf8")).toBe("hello job");

      // copyItem with missing source
      expect(copyItem(join(dir, "missing.txt"), join(dir, "out.txt"))).toBe(true);

      // copyDirInto
      const srcDir = join(dir, "dir-src");
      const dstDir = join(dir, "dir-dst");
      mkdirSync(srcDir, { recursive: true });
      writeFileSync(join(srcDir, "inner.txt"), "inner");

      expect(copyDirInto(srcDir, dstDir)).toBe(true);
      expect(existsSync(join(dstDir, "inner.txt"))).toBe(true);

      // copyDirInto with missing dir
      expect(copyDirInto(join(dir, "missing-dir"), join(dir, "out-dir"))).toBe(true);

      const success = await runJobsWithPreserve(
        [
          { kind: "File", src: srcFile, dst: dstFile },
          { kind: "Dir", src: srcDir, dst: dstDir, scope: "Children" },
        ],
        new Map(),
      );
      expect(success).toBe(true);
    });
  });
});

describe("core/index.ts", () => {
  test("parseTimeoutSeconds, syncTimeout, syncLockPath, tryAcquireSyncLock", async () => {
    await withTempDir(async (dir) => {
      const syncEnv = SyncEnv.fromHome(dir, 1000);
      expect(parseTimeoutSeconds("30", 10)).toBe(30);
      expect(parseTimeoutSeconds("invalid", 10)).toBe(10);
      expect(syncTimeout()).toBe(900);
      expect(syncLockPath(syncEnv).includes("sync.lock")).toBe(true);

      const lock = tryAcquireSyncLock(syncEnv);
      expect(lock).toBeDefined();
      if (lock) {
        releaseSyncLock(lock);
      }
    });
  });

  test("runSync and main full execution", async () => {
    await withTempDir(async (dir) => {
      const ssot = join(dir, ".config", "agents");
      mkdirSync(join(ssot, "tools", "cliproxyapi"), { recursive: true });
      writeFileSync(
        join(ssot, "tools", "cliproxyapi", "deployment.json"),
        JSON.stringify({
          server: { hostname: hostname() },
          listen: { host: "127.0.0.1", port: 9443 },
          client: { baseUrl: "https://127.0.0.1:9443/v1" },
        }),
      );
      mkdirSync(join(ssot, "skills", "current"), { recursive: true });
      writeFileSync(join(ssot, "skills", "current", "skill.txt"), "test skill");
      writeFileSync(join(ssot, "HARNESS.md"), "instruction");

      const syncEnv = SyncEnv.fromHome(dir, 1000);
      const success = await runSync(syncEnv, { warnManagedServices: true });
      expect(success).toBe(true);
    });
  });

  test("launchMain with unsupported and valid harness", async () => {
    await withTempDir(async (_dir) => {
      const exitCode = await launchMain("non_existent_tool_123", []);
      expect(exitCode).toBe(2);
    });
  });

  test("launchMain with tool target", async () => {
    const originalHome = Bun.env["HOME"];
    await withTempDir(async (dir) => {
      Bun.env["HOME"] = dir;
      try {
        const exitCode = await launchMain("non_existent_tool_xyz", ["--version"]);
        expect(exitCode).toBe(2);
      } finally {
        Bun.env["HOME"] = originalHome;
      }
    });
  });
});
