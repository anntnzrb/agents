import { describe, expect, test } from "bun:test";
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { SyncEnv } from "@core/harness.ts";
import { pruneUnreferencedReleases, runJobsWithPreserve } from "@core/jobs.ts";
import { buildSyncPlan } from "@core/plan.ts";
import { sharedToolCacheEnv } from "./support/cache-env.ts";

const makeHome = (options: { gatewayHost?: boolean } = {}): string => {
  const home = mkdtempSync(join(tmpdir(), "runtime-install-test-"));
  const tools = join(home, ".config", "agents", "tools");
  mkdirSync(join(tools, "cliproxyapi"), { recursive: true });
  mkdirSync(join(tools, "mcporter"), { recursive: true });
  mkdirSync(join(tools, "summarize"), { recursive: true });
  const deployment = {
    server: { hostname: options.gatewayHost === false ? "test-gateway" : hostname() },
    listen: { host: "127.0.0.1", port: 9443 },
    client: { baseUrl: "http://127.0.0.1:9443/v1" },
  };
  writeFileSync(join(tools, "cliproxyapi", "deployment.json"), `${JSON.stringify(deployment)}\n`);
  writeFileSync(join(tools, "mcporter", "mcporter.jsonc"), "{}\n");
  writeFileSync(join(tools, "summarize", "config.json"), "{}\n");
  return home;
};
const seedSourceRoot = (home: string, cliContent = 'console.log("ok");\n'): string => {
  const repoSync = join(import.meta.dir, "..");
  const sourceRoot = join(home, ".config", "agents", "sync");
  mkdirSync(sourceRoot, { recursive: true });
  cpSync(join(repoSync, "src"), join(sourceRoot, "src"), { recursive: true });
  for (const file of ["package.json", "tsconfig.json", "bun.lock"]) {
    copyFileSync(join(repoSync, file), join(sourceRoot, file));
  }
  writeFileSync(join(sourceRoot, "src", "cli.ts"), cliContent);
  return sourceRoot;
};

const runtimeInstallJob = (home: string) => {
  const syncEnv = SyncEnv.fromHome(home, 60_000, { platform: "linux" });
  const plan = buildSyncPlan(syncEnv);
  const job = plan.jobs.find((j) => j.kind === "SyncRuntimeInstall");
  expect(job?.kind).toBe("SyncRuntimeInstall");
  return { syncEnv, job: job! };
};

const readDirNames = (root: string): string[] => {
  if (!existsSync(root)) {
    return [];
  }
  return readdirSync(root)
    .filter((name) => !name.startsWith("."))
    .toSorted();
};

describe("SyncRuntimeInstall job", () => {
  test("plan includes the job with new runtime paths", () => {
    const home = makeHome();
    try {
      seedSourceRoot(home);
      const { syncEnv, job } = runtimeInstallJob(home);
      expect(job.sourceRoot).toBe(join(syncEnv.ssotHome, "sync"));
      expect(job.releasesRoot).toBe(join(syncEnv.runtimeHome, "sync-releases"));
      expect(job.currentLink).toBe(join(syncEnv.runtimeHome, "sync-current"));
      expect(job.timeoutMs).toBeGreaterThan(0);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("publishes current link and installs dependencies", async () => {
    const home = makeHome();
    try {
      seedSourceRoot(home);
      const { job } = runtimeInstallJob(home);
      const ok = await runJobsWithPreserve([job]);
      expect(ok).toBe(true);
      const currentLink = join(home, ".local", "share", "agents", "sync-current");
      expect(existsSync(currentLink)).toBe(true);
      const releaseDir = realpathSync(currentLink);
      expect(existsSync(join(releaseDir, "src", "cli.ts"))).toBe(true);
      expect(existsSync(join(releaseDir, "node_modules"))).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("fails and leaves current link untouched when lockfile is missing", async () => {
    const home = makeHome();
    try {
      seedSourceRoot(home);
      rmSync(join(home, ".config", "agents", "sync", "bun.lock"));
      const { job } = runtimeInstallJob(home);
      const ok = await runJobsWithPreserve([job]);
      expect(ok).toBe(false);
      expect(existsSync(job.currentLink)).toBe(false);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("fails and removes stage on broken package.json", async () => {
    const home = makeHome();
    try {
      seedSourceRoot(home);
      writeFileSync(join(home, ".config", "agents", "sync", "package.json"), "{ broken");
      const { job } = runtimeInstallJob(home);
      const ok = await runJobsWithPreserve([job]);
      expect(ok).toBe(false);
      expect(existsSync(job.currentLink)).toBe(false);
      const all = existsSync(job.releasesRoot) ? readdirSync(job.releasesRoot) : [];
      expect(all.some((name) => name.startsWith(".stage-"))).toBe(false);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("installs new release and updates current link without pruning previous release", async () => {
    const home = makeHome();
    try {
      const sourceRoot = seedSourceRoot(home);
      const { job } = runtimeInstallJob(home);
      const ok = await runJobsWithPreserve([job]);
      expect(ok).toBe(true);
      const firstReleases = readDirNames(job.releasesRoot);
      expect(firstReleases.length).toBe(1);

      writeFileSync(join(sourceRoot, "src", "cli.ts"), 'console.log("updated");\n');
      const { job: job2 } = runtimeInstallJob(home);
      const ok2 = await runJobsWithPreserve([job2]);
      expect(ok2).toBe(true);
      const secondReleases = readDirNames(job2.releasesRoot);
      expect(secondReleases.length).toBe(2);
      expect(secondReleases).toContain(firstReleases[0]!);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("runtime installation cleans up temporary stage on install failure", async () => {
    const home = makeHome();
    try {
      const sourceRoot = seedSourceRoot(home);
      // Corrupt package.json so bun install fails
      writeFileSync(
        join(sourceRoot, "package.json"),
        JSON.stringify({
          name: "sync",
          version: "0.1.0",
          dependencies: {
            "non-existent-package-that-will-fail-install-xyz": "99.99.99",
          },
        }),
      );

      const { job } = runtimeInstallJob(home);
      const success = await runJobsWithPreserve([job]);
      expect(success).toBe(false);

      // Ensure releasesRoot has no leftover .stage-* directories
      if (existsSync(job.releasesRoot)) {
        const entries = readdirSync(job.releasesRoot);
        const stages = entries.filter((name) => name.startsWith(".stage-"));
        expect(stages).toEqual([]);
      }
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("pruneUnreferencedReleases cleans complete unreferenced releases and stale stages while preserving active release, active stages, and unrecognized dirs", async () => {
    const home = makeHome();
    try {
      const sourceRoot = seedSourceRoot(home);
      const { job } = runtimeInstallJob(home);
      await runJobsWithPreserve([job]);
      const firstRelease = realpathSync(job.currentLink);
      expect(firstRelease).toBeDefined();
      const firstReleaseName = readDirNames(job.releasesRoot)[0];

      writeFileSync(join(sourceRoot, "src", "cli.ts"), 'console.log("updated");\n');
      const { job: job2 } = runtimeInstallJob(home);
      await runJobsWithPreserve([job2]);

      // Seed unrecognized directory, dotfile, and incomplete sha256 directory
      const unrecognizedDir = join(job.releasesRoot, "custom-unrecognized-dir");
      mkdirSync(unrecognizedDir, { recursive: true });
      writeFileSync(join(unrecognizedDir, "data.txt"), "preserve-me");

      const stageDotfile = join(job.releasesRoot, ".stage-test-keep");
      mkdirSync(stageDotfile, { recursive: true });
      writeFileSync(join(stageDotfile, "tmp.txt"), "stage-temp");

      const incompleteShaDir = join(job.releasesRoot, "a".repeat(64));
      mkdirSync(incompleteShaDir, { recursive: true });
      writeFileSync(join(incompleteShaDir, "incomplete.txt"), "incomplete");

      // Seed a stale stage with a dead PID (e.g. 99999999)
      const deadPidStage = join(job.releasesRoot, ".stage-99999999-deadbeef12345678");
      mkdirSync(deadPidStage, { recursive: true });
      writeFileSync(join(deadPidStage, "package.json"), "{}");

      // Seed an active stage with the current process PID (live process)
      const livePidStage = join(job.releasesRoot, `.stage-${process.pid}-livebeef12345678`);
      mkdirSync(livePidStage, { recursive: true });
      writeFileSync(join(livePidStage, "package.json"), "{}");

      // Prune
      pruneUnreferencedReleases(job2.releasesRoot, job2.currentLink);

      const remaining = readdirSync(job2.releasesRoot);
      // Preserved items:
      expect(remaining).toContain(".stage-test-keep");
      expect(remaining).toContain("custom-unrecognized-dir");
      expect(remaining).toContain("a".repeat(64));
      expect(remaining).toContain(`.stage-${process.pid}-livebeef12345678`);

      const currentReleaseName = readDirNames(job2.releasesRoot).find(
        (name) => name !== "custom-unrecognized-dir" && name !== "a".repeat(64),
      );
      expect(currentReleaseName).toBeDefined();
      expect(remaining).toContain(currentReleaseName!);

      // Cleaned up items:
      expect(remaining).not.toContain(firstReleaseName);
      expect(remaining).not.toContain(".stage-99999999-deadbeef12345678");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("runSync removes the legacy mutable runtime after current link and wrappers", async () => {
    const home = makeHome({ gatewayHost: false });
    try {
      const legacy = join(home, ".local", "share", "agents", "sync");
      mkdirSync(join(legacy, "src"), { recursive: true });
      writeFileSync(join(legacy, "src", "cli.ts"), "console.log('legacy');");
      seedSourceRoot(home);
      const proc = Bun.spawnSync(
        [
          process.execPath,
          "-e",
          `import { SyncEnv } from "@core/harness.ts";
import { runSync } from "@core/index.ts";
globalThis.fetch = async () => new Response(null, { status: 503 });
const syncEnv = SyncEnv.fromHome(${JSON.stringify(home)}, 60_000, { platform: "linux" });
const ok = await runSync(syncEnv);
process.exit(ok ? 0 : 1);`,
        ],
        {
          cwd: resolve(import.meta.dir, ".."),
          env: {
            ...Bun.env,
            ...sharedToolCacheEnv,
            HOME: home,
          },
        },
      );
      expect(proc.exitCode).toBe(0);
      expect(existsSync(legacy)).toBe(false);
      const currentLink = join(home, ".local", "share", "agents", "sync-current");
      expect(existsSync(currentLink)).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  }, 30_000);

  test("runSync prunes old releases after wrapper reconciliation succeeds and preserves unrecognized directories", async () => {
    const home = makeHome({ gatewayHost: false });
    try {
      seedSourceRoot(home);
      // First run to create initial release
      const proc1 = Bun.spawnSync(
        [
          process.execPath,
          "-e",
          `import { SyncEnv } from "@core/harness.ts";
import { runSync } from "@core/index.ts";
globalThis.fetch = async () => new Response(null, { status: 503 });
const syncEnv = SyncEnv.fromHome(${JSON.stringify(home)}, 60_000, { platform: "linux" });
const ok = await runSync(syncEnv);
process.exit(ok ? 0 : 1);`,
        ],
        {
          cwd: resolve(import.meta.dir, ".."),
          env: {
            ...Bun.env,
            ...sharedToolCacheEnv,
            HOME: home,
          },
        },
      );
      expect(proc1.exitCode).toBe(0);

      const releasesRoot = join(home, ".local", "share", "agents", "sync-releases");
      const firstRelease = readDirNames(releasesRoot)[0];

      // Add unrecognized dir
      const unrecognized = join(releasesRoot, "my-custom-backup");
      mkdirSync(unrecognized, { recursive: true });
      writeFileSync(join(unrecognized, "file.txt"), "data");

      // Update source
      writeFileSync(
        join(home, ".config", "agents", "sync", "src", "cli.ts"),
        'console.log("v2");\n',
      );

      // Second run
      const proc2 = Bun.spawnSync(
        [
          process.execPath,
          "-e",
          `import { SyncEnv } from "@core/harness.ts";
import { runSync } from "@core/index.ts";
globalThis.fetch = async () => new Response(null, { status: 503 });
const syncEnv = SyncEnv.fromHome(${JSON.stringify(home)}, 60_000, { platform: "linux" });
const ok = await runSync(syncEnv);
process.exit(ok ? 0 : 1);`,
        ],
        {
          cwd: resolve(import.meta.dir, ".."),
          env: {
            ...Bun.env,
            ...sharedToolCacheEnv,
            HOME: home,
          },
        },
      );
      expect(proc2.exitCode).toBe(0);

      const remaining = readdirSync(releasesRoot);
      expect(remaining).toContain("my-custom-backup");
      expect(remaining).not.toContain(firstRelease);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  }, 30_000);

  test("runSync preserves previous releases when wrapper reconciliation fails", async () => {
    const home = makeHome({ gatewayHost: false });
    try {
      seedSourceRoot(home);
      // First run to create initial release
      const proc1 = Bun.spawnSync(
        [
          process.execPath,
          "-e",
          `import { SyncEnv } from "@core/harness.ts";
import { runSync } from "@core/index.ts";
globalThis.fetch = async () => new Response(null, { status: 503 });
const syncEnv = SyncEnv.fromHome(${JSON.stringify(home)}, 60_000, { platform: "linux" });
const ok = await runSync(syncEnv);
process.exit(ok ? 0 : 1);`,
        ],
        {
          cwd: resolve(import.meta.dir, ".."),
          env: {
            ...Bun.env,
            ...sharedToolCacheEnv,
            HOME: home,
          },
        },
      );
      expect(proc1.exitCode).toBe(0);

      const releasesRoot = join(home, ".local", "share", "agents", "sync-releases");
      const firstRelease = readDirNames(releasesRoot)[0];

      // Update source
      writeFileSync(
        join(home, ".config", "agents", "sync", "src", "cli.ts"),
        'console.log("v2");\n',
      );

      // Block wrapper directory so reconcileWrappers fails
      rmSync(join(home, ".local", "bin"), { recursive: true, force: true });
      writeFileSync(join(home, ".local", "bin"), "blocking-file-not-dir");

      // Second run fails at wrappers
      const proc2 = Bun.spawnSync(
        [
          process.execPath,
          "-e",
          `import { SyncEnv } from "@core/harness.ts";
import { runSync } from "@core/index.ts";
globalThis.fetch = async () => new Response(null, { status: 503 });
const syncEnv = SyncEnv.fromHome(${JSON.stringify(home)}, 60_000, { platform: "linux" });
const ok = await runSync(syncEnv);
process.exit(ok ? 0 : 1);`,
        ],
        {
          cwd: resolve(import.meta.dir, ".."),
          env: {
            ...Bun.env,
            ...sharedToolCacheEnv,
            HOME: home,
          },
        },
      );
      expect(proc2.exitCode).toBe(1);

      // Previous release must NOT have been pruned!
      const remaining = readdirSync(releasesRoot);
      expect(remaining).toContain(firstRelease!);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  }, 30_000);
});
