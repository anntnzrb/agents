import { beforeEach, spyOn, test } from "bun:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join } from "node:path";
import { SyncEnv } from "@core/harness.ts";
import { runJobsWithPreserve } from "@core/jobs.ts";
import { buildSyncPlan, type Job } from "@core/plan.ts";

const DEPLOYMENT = {
  server: { hostname: hostname() },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
} as const;

beforeEach(() => {
  spyOn(console, "error").mockImplementation(() => {});
});

function makeHome(): string {
  const home = mkdtempSync(join(tmpdir(), "runtime-install-test-"));
  const tools = join(home, ".config", "agents", "tools", "cliproxyapi");
  mkdirSync(tools, { recursive: true });
  writeFileSync(join(tools, "deployment.json"), `${JSON.stringify(DEPLOYMENT)}\n`);
  return home;
}

function seedRuntimeManifest(home: string): void {
  const sourceRoot = join(home, ".config", "agents", "sync");
  mkdirSync(sourceRoot, { recursive: true });
  writeFileSync(join(sourceRoot, "package.json"), `${JSON.stringify({ name: "fixture" })}\n`);
  writeFileSync(join(sourceRoot, "bun.lock"), "{}\n");
}

test("sync_plan_deploys_runtime_manifest_and_installs_dependencies", () => {
  const home = makeHome();
  try {
    seedRuntimeManifest(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const plan = buildSyncPlan(syncEnv);
    const runtimeRoot = join(syncEnv.runtimeHome, "sync");

    const manifestIndex = plan.jobs.findIndex(
      (job) => job.kind === "File" && job.dst === join(runtimeRoot, "package.json"),
    );
    const lockIndex = plan.jobs.findIndex(
      (job) => job.kind === "File" && job.dst === join(runtimeRoot, "bun.lock"),
    );
    const installIndex = plan.jobs.findIndex((job) => job.kind === "BunInstall");

    assert.notEqual(manifestIndex, -1, "package.json file job");
    assert.notEqual(lockIndex, -1, "bun.lock file job");
    assert.notEqual(installIndex, -1, "BunInstall job");
    const installJob = plan.jobs[installIndex];
    assert.ok(installJob?.kind === "BunInstall");
    assert.equal(installJob.root, runtimeRoot);
    assert.ok(installJob.timeoutMs > 0);
    assert.ok(installIndex > manifestIndex && installIndex > lockIndex);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("sync_plan_skips_install_job_without_source_lockfile", () => {
  const home = makeHome();
  try {
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const plan = buildSyncPlan(syncEnv);
    assert.equal(
      plan.jobs.some((job) => job.kind === "BunInstall"),
      false,
    );
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("bun_install_job_installs_production_dependencies_offline", async () => {
  const root = mkdtempSync(join(tmpdir(), "bun-install-job-"));
  try {
    mkdirSync(join(root, "vendor", "tiny"), { recursive: true });
    writeFileSync(
      join(root, "vendor", "tiny", "package.json"),
      `${JSON.stringify({ name: "tiny", version: "1.0.0" })}\n`,
    );
    writeFileSync(
      join(root, "package.json"),
      `${JSON.stringify({
        name: "fixture",
        private: true,
        dependencies: { tiny: "file:./vendor/tiny" },
      })}\n`,
    );
    const seed = Bun.spawnSync(["bun", "install"], { cwd: root, stdout: "ignore", stderr: "pipe" });
    assert.equal(seed.exitCode, 0);

    rmSync(join(root, "node_modules"), { recursive: true, force: true });

    const jobs: readonly Job[] = [{ kind: "BunInstall", root, timeoutMs: 60_000 }];
    assert.equal(await runJobsWithPreserve(jobs), true);
    assert.ok(existsSync(join(root, "node_modules", "tiny")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("bun_install_job_fails_on_broken_manifest", async () => {
  const root = mkdtempSync(join(tmpdir(), "bun-install-job-broken-"));
  try {
    writeFileSync(join(root, "package.json"), "{ broken");
    const jobs: readonly Job[] = [{ kind: "BunInstall", root, timeoutMs: 60_000 }];
    assert.equal(await runJobsWithPreserve(jobs), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
