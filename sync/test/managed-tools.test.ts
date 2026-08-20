import { test } from "bun:test";
import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { CliProxyDeployment } from "@core/cliproxy-deployment.ts";
import { SyncEnv } from "@core/harness.ts";
import { isCliProxyRunning, prepareManagedTools } from "@core/managed-tools.ts";

const ARCHIVE = "fixture archive";
const CHECKSUM = new Bun.CryptoHasher("sha256").update(ARCHIVE).digest("hex");
const DEPLOYMENT: CliProxyDeployment = {
  server: { hostname: "test-gateway" },
  listen: { host: "100.64.0.42", port: 9443 },
  client: { baseUrl: "https://gateway.example.test:9443/v1" },
};

function withTempHome<T>(fn: (home: string) => T | Promise<T>): Promise<T> {
  const home = mkdtempSync(join(tmpdir(), "agents-managed-tool-test-"));
  return Promise.resolve(fn(home)).finally(() => {
    rmSync(home, { recursive: true, force: true });
  });
}

function writeManifest(home: string, checksum = CHECKSUM): void {
  const cliProxyAssets = join(home, ".config", "agents", "tools", "cliproxyapi");
  mkdirSync(cliProxyAssets, { recursive: true });
  writeFileSync(
    join(cliProxyAssets, "release.json"),
    `${JSON.stringify({
      repository: "router-for-me/CLIProxyAPI",
      version: "7.2.132",
      binary: "cli-proxy-api",
      assets: {
        "darwin-arm64": {
          name: "CLIProxyAPI_7.2.132_darwin_aarch64.tar.gz",
          sha256: checksum,
        },
      },
    })}\n`,
  );
}

test("managed_tool_downloads_verified_release_once", async () => {
  await withTempHome(async (home) => {
    writeManifest(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "darwin" });
    let downloads = 0;
    const runtime = {
      arch: "arm64" as const,
      cacheHome: join(home, "cache"),
      download: async (url: string, destination: string): Promise<void> => {
        downloads += 1;
        assert.equal(url.includes("/releases/download/v7.2.132/"), true);
        writeFileSync(destination, ARCHIVE);
      },
      extract: async (_archive: string, destination: string, entryName: string): Promise<void> => {
        assert.equal(entryName, "cli-proxy-api");
        const executable = join(destination, entryName);
        writeFileSync(executable, "#!/bin/sh\nexit 0\n");
        chmodSync(executable, 0o755);
      },
    };

    const [first] = await prepareManagedTools(syncEnv, runtime);
    assert.ok(first);
    assert.equal(first.version, "7.2.132");
    assert.equal(first.command, "cli-proxy-api");
    assert.equal(existsSync(first.executable), true);
    assert.equal(readFileSync(first.executable, "utf8"), "#!/bin/sh\nexit 0\n");

    const [second] = await prepareManagedTools(syncEnv, runtime);
    assert.equal(second?.executable, first.executable);
    assert.equal(downloads, 1);
  });
});

test("managed_tool_rejects_checksum_mismatch", async () => {
  await withTempHome(async (home) => {
    writeManifest(home, "0".repeat(64));
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "darwin" });
    await assert.rejects(
      prepareManagedTools(syncEnv, {
        arch: "arm64",
        cacheHome: join(home, "cache"),
        download: async (_url, destination): Promise<void> => {
          writeFileSync(destination, ARCHIVE);
        },
      }),
      /checksum mismatch/,
    );
  });
});

test("managed_tool_rejects_platform_without_pinned_asset", async () => {
  await withTempHome(async (home) => {
    writeManifest(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    await assert.rejects(
      prepareManagedTools(syncEnv, { arch: "arm64", cacheHome: join(home, "cache") }),
      /no release asset for linux-arm64/,
    );
  });
});

test("managed_tool_health_check_targets_deployment_client", async () => {
  const calls: string[] = [];
  const healthy = await isCliProxyRunning(DEPLOYMENT, 500, async (input) => {
    calls.push(
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
    );
    return new Response(null, { status: 503 });
  });

  assert.equal(healthy, true);
  assert.deepEqual(calls, ["https://gateway.example.test:9443/v1/models"]);
});
