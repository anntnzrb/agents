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
import { join } from "node:path";
import { SyncEnv } from "@core/harness.ts";
import { runSync } from "@core/index.ts";
import { runJobsWithPreserve } from "@core/jobs.ts";
import { buildSyncPlan } from "@core/plan.ts";

const makeHome = (options: { gatewayHost?: boolean } = {}): string => {
  const home = mkdtempSync(join(tmpdir(), "runtime-install-test-"));
  const tools = join(home, ".config", "agents", "tools", "cliproxyapi");
  mkdirSync(tools, { recursive: true });
  const deployment = {
    server: { hostname: options.gatewayHost === false ? "test-gateway" : hostname() },
    listen: { host: "127.0.0.1", port: 9443 },
    client: { baseUrl: "http://127.0.0.1:9443/v1" },
  };
  writeFileSync(join(tools, "deployment.json"), `${JSON.stringify(deployment)}\n`);
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

  test("reuses an existing release and prunes an old one", async () => {
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
      expect(secondReleases.length).toBe(1);
      expect(secondReleases[0]).not.toBe(firstReleases[0]);
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
      const syncEnv = SyncEnv.fromHome(home, 60_000, { platform: "linux" });
      const originalFetch = globalThis.fetch;
      globalThis.fetch = (async () =>
        new Response(null, { status: 503 })) as unknown as typeof fetch;
      try {
        const ok = await runSync(syncEnv);
        expect(ok).toBe(true);
      } finally {
        globalThis.fetch = originalFetch;
      }
      expect(existsSync(legacy)).toBe(false);
      const currentLink = join(home, ".local", "share", "agents", "sync-current");
      expect(existsSync(currentLink)).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
