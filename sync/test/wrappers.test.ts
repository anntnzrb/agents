import { test } from "bun:test";
import assert from "node:assert/strict";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { buildHarness, SyncEnv, supportedHarness } from "@core/harness.ts";
import {
  managedToolWrapperDestination,
  reconcileWrapperFiles,
  reconcileWrappers,
  renderWrapper,
  WRAPPER_MARKER,
  WRAPPER_STATE_FILE,
  wrapperDestinations,
} from "@core/wrappers.ts";

function withTempHome<T>(fn: (home: string) => T): T {
  const root = mkdtempSync(join(tmpdir(), "agents-wrapper-test-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function addHarnessSources(
  home: string,
  ids = ["codex", "deepseek", "opencode", "pi", "omp"],
): void {
  for (const id of ids) {
    mkdirSync(join(home, ".config", "agents", "harnesses", id), { recursive: true });
  }
}

test("harnesses_are_discovered_from_known_harness_directories", () => {
  withTempHome((home) => {
    addHarnessSources(home, ["codex", "opencode"]);
    mkdirSync(join(home, ".config", "agents", "harnesses", "unrelated"), { recursive: true });
    writeFileSync(join(home, ".config", "agents", "harnesses", "pi"), "not a directory");

    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    assert.deepEqual(
      syncEnv.harnesses.map((harness) => harness.sourceName),
      ["codex", "opencode"],
    );
    assert.equal(syncEnv.platform, "linux");
  });
});

test("harness_ownership_ids_cannot_escape_the_wrapper_directory", () => {
  assert.throws(
    () =>
      buildHarness({
        id: "codex",
        sourceName: "../codex",
        home: "/tmp/codex",
        launcher: { package: "@openai/codex", bin: "codex" },
      }),
    /invalid harness id/,
  );
});

test("installed_runtime_resolves_known_harness_without_ssot", () => {
  withTempHome((home) => {
    assert.equal(existsSync(join(home, ".config", "agents")), false);
    const deepseek = supportedHarness(home, "deepseek", "linux");
    assert.equal(deepseek?.home, join(home, ".dsh"));
    assert.equal(deepseek?.launcher.package, "@deepseek-ai/dsh");
    assert.equal(deepseek?.launcher.bin, "dsh");
    assert.equal(supportedHarness(home, "pi", "linux")?.home, join(home, ".pi"));
    assert.equal(supportedHarness(home, "unknown", "linux"), undefined);
  });
});

test("wrapper_destinations_render_unix_launchers", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const unixEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const unix = wrapperDestinations(unixEnv);
    assert.equal(unix[0]?.path, join(home, ".local", "bin", "codex"));
    assert.equal(unix[0]?.content.startsWith("#!/bin/sh\n"), true);
    assert.equal(unix[0]?.content.includes(WRAPPER_MARKER), true);
    assert.equal(unix[0]?.content.includes("launch 'codex'"), true);
    assert.equal(unix[0]?.content.includes("exit 127"), true);
    assert.equal(unix[0]?.content.includes("sync runtime is missing"), true);
    assert.equal(
      unix[0]?.content.includes(join(home, ".local", "share", "agents", "sync", "src", "cli.ts")),
      true,
    );
    assert.equal(unix[0]?.content.includes(join(home, ".config", "agents")), false);
    const deepseekUnix = unix.find((entry) => entry.path.endsWith("/dsh"));
    assert.equal(deepseekUnix?.path, join(home, ".local", "bin", "dsh"));
    assert.equal(deepseekUnix?.content.includes("launch 'deepseek'"), true);

    const mcporterUnix = unix.find((entry) => entry.path.endsWith("/mcporter"));
    assert.equal(mcporterUnix?.path, join(home, ".local", "bin", "mcporter"));
    assert.equal(mcporterUnix?.content.includes("launch 'mcporter'"), true);
    assert.equal(
      mcporterUnix?.content.includes(`'--config' '${join(home, ".mcporter", "mcporter.json")}'`),
      true,
    );
    assert.equal(mcporterUnix?.content.includes(WRAPPER_MARKER), true);

    assert.equal(renderWrapper(unixEnv, unixEnv.harnesses[0]!), unix[0]!.content);
  });
});

test("codex_wrapper defers sandbox and hook policies to config", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const unixEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const destinations = wrapperDestinations(unixEnv);
    const codex = destinations.find((entry) => entry.path.endsWith("/codex"));
    assert.ok(codex, "codex wrapper destination exists");
    const bypassSandbox = codex.content.indexOf("--dangerously-bypass-approvals-and-sandbox");
    const bypassHookTrust = codex.content.indexOf("--dangerously-bypass-hook-trust");
    assert.equal(bypassSandbox, -1, "codex wrapper must not override agent permission profiles");
    assert.equal(bypassHookTrust, -1, "codex wrapper must not bypass hook trust");
    for (const entry of destinations) {
      if (entry.path.endsWith("/codex")) {
        continue;
      }
      assert.equal(
        entry.content.includes("--dangerously-bypass-approvals-and-sandbox"),
        false,
        `${entry.path} wrapper carries codex yolo flags`,
      );
      assert.equal(
        entry.content.includes("--dangerously-bypass-hook-trust"),
        false,
        `${entry.path} wrapper carries codex hook-trust flag`,
      );
    }
  });
});

test("managed_tool_wrappers_use_the_cached_binary_and_generated_config", () => {
  withTempHome((home) => {
    const tool = {
      name: "cliproxyapi",
      command: "cli-proxy-api",
      executable: join(home, ".cache", "cli-proxy-api"),
      version: "7.2.132",
      configPath: join(home, ".cli-proxy-api", "config.yaml"),
    };
    const unixEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const unix = managedToolWrapperDestination(unixEnv, tool);
    assert.equal(unix.path, join(home, ".local", "bin", "cli-proxy-api"));
    assert.equal(unix.content.includes(tool.executable), true);
    assert.equal(unix.content.includes(`--config '${tool.configPath}'`), true);
  });
});

test("wrapper_reconciliation_is_idempotent_and_removes_owned_stale_entries", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const first = reconcileWrappers(syncEnv);
    assert.equal(first, true);
    const destinations = wrapperDestinations(syncEnv);
    const codex = destinations[0]!;
    const before = statSync(codex.path);
    assert.equal(lstatSync(codex.path).isFile(), true);

    assert.equal(reconcileWrappers(syncEnv), true);
    const after = statSync(codex.path);
    assert.equal(after.ino, before.ino);
    assert.equal(readFileSync(codex.path, "utf8").includes(WRAPPER_MARKER), true);

    const withoutOmp = destinations.filter((entry) => !entry.path.endsWith("/omp"));
    const result = reconcileWrapperFiles(syncEnv, withoutOmp);
    assert.equal(
      result.removed.some((entry) => entry.endsWith("/omp")),
      true,
    );
    assert.equal(existsSync(join(home, ".local", "bin", "omp")), false);
    assert.equal(existsSync(join(home, ".local", "bin", "codex")), true);
    assert.equal(existsSync(join(syncEnv.managedStateHome, WRAPPER_STATE_FILE)), true);
  });
});

test("wrapper_reconciliation_preserves_unmanaged_conflicts", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const destination = wrapperDestinations(syncEnv)[0]!;
    mkdirSync(join(home, ".local", "bin"), { recursive: true });
    writeFileSync(destination.path, "#!/bin/sh\necho user-owned\n", "utf8");

    assert.equal(reconcileWrappers(syncEnv), true);
    assert.equal(readFileSync(destination.path, "utf8"), "#!/bin/sh\necho user-owned\n");
    assert.equal(
      readFileSync(join(syncEnv.managedStateHome, WRAPPER_STATE_FILE), "utf8").includes(
        destination.path,
      ),
      false,
    );

    // A stale state entry outside the canonical wrapper directory is never a
    // deletion authority, even if the file carries our marker.
    const outside = join(home, "outside-wrapper");
    writeFileSync(outside, `# ${WRAPPER_MARKER}\n`, "utf8");
    writeFileSync(
      join(syncEnv.managedStateHome, WRAPPER_STATE_FILE),
      `${JSON.stringify({ version: 1, entries: [outside] })}\n`,
      "utf8",
    );
    reconcileWrapperFiles(syncEnv, []);
    assert.equal(existsSync(outside), true);
  });
});
