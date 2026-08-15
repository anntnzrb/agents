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

import { buildHarness, SyncEnv } from "@core/harness.ts";
import {
  reconcileWrapperFiles,
  reconcileWrappers,
  renderWrapper,
  WINDOWS_PATH_MARKER_FILE,
  WRAPPER_MARKER,
  WRAPPER_STATE_FILE,
  wrapperDestinations,
  wrapperDirectory,
} from "@core/wrappers.ts";

function withTempHome<T>(fn: (home: string) => T): T {
  const root = mkdtempSync(join(tmpdir(), "agents-wrapper-test-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function addHarnessSources(home: string, ids = ["codex", "opencode", "pi", "omp"]): void {
  for (const id of ids) {
    mkdirSync(join(home, ".config", "agents", "tools", id), { recursive: true });
  }
}

test("harnesses_are_discovered_from_known_tool_directories", () => {
  withTempHome((home) => {
    addHarnessSources(home, ["codex", "opencode"]);
    mkdirSync(join(home, ".config", "agents", "tools", "unrelated"), { recursive: true });
    writeFileSync(join(home, ".config", "agents", "tools", "pi"), "not a directory");

    const syncEnv = SyncEnv.fromHome(home, 1000, {
      platform: "win32",
      localAppData: join(home, "local-app-data"),
    });
    assert.deepEqual(
      syncEnv.harnesses.map((harness) => harness.sourceName),
      ["codex", "opencode"],
    );
    assert.equal(syncEnv.platform, "win32");
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

test("wrapper_destinations_render_unix_and_windows_launchers", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const unixEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const unix = wrapperDestinations(unixEnv, "linux");
    assert.equal(unix[0]?.path, join(home, ".local", "bin", "codex"));
    assert.equal(unix[0]?.content.startsWith("#!/bin/sh\n"), true);
    assert.equal(unix[0]?.content.includes(WRAPPER_MARKER), true);
    assert.equal(unix[0]?.content.includes("launch 'codex'"), true);

    const windowsEnv = SyncEnv.fromHome(home, 1000, {
      platform: "win32",
      localAppData: join(home, "local-app-data"),
    });
    const windows = wrapperDestinations(windowsEnv, "win32");
    assert.equal(
      windows[0]?.path,
      join(home, "local-app-data", "Programs", "Agents", "bin", "codex.cmd"),
    );
    assert.equal(windows[0]?.content.startsWith("@echo off\r\n"), true);
    assert.equal(windows[0]?.content.includes(`rem ${WRAPPER_MARKER}`), true);
    assert.equal(windows[0]?.content.endsWith("%ERRORLEVEL%\r\n"), true);
    assert.equal(renderWrapper(unixEnv, unixEnv.harnesses[0]!, "linux"), unix[0]!.content);
  });
});

test("wrapper_reconciliation_is_idempotent_and_removes_owned_stale_entries", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    const first = reconcileWrappers(syncEnv);
    assert.equal(first, true);
    const destinations = wrapperDestinations(syncEnv, "linux");
    const codex = destinations[0]!;
    const before = statSync(codex.path);
    assert.equal(lstatSync(codex.path).isFile(), true);

    assert.equal(reconcileWrappers(syncEnv), true);
    const after = statSync(codex.path);
    assert.equal(after.ino, before.ino);
    assert.equal(readFileSync(codex.path, "utf8").includes(WRAPPER_MARKER), true);

    const withoutOmp = destinations.filter((entry) => entry.harness.sourceName !== "omp");
    const result = reconcileWrapperFiles(syncEnv, withoutOmp, "linux");
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
    const destination = wrapperDestinations(syncEnv, "linux")[0]!;
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
    reconcileWrapperFiles(syncEnv, [], "linux");
    assert.equal(existsSync(outside), true);
  });
});

test("windows_path_marker_is_durable_and_path_hook_runs_once", () => {
  withTempHome((home) => {
    addHarnessSources(home);
    const syncEnv = SyncEnv.fromHome(home, 1000, {
      platform: "win32",
      localAppData: join(home, "local-app-data"),
    });
    let calls = 0;
    const writeWindowsPath = (): boolean => {
      calls += 1;
      return true;
    };
    assert.equal(reconcileWrappers(syncEnv, { writeWindowsPath }), true);
    assert.equal(reconcileWrappers(syncEnv, { writeWindowsPath }), true);
    assert.equal(calls, 1);
    assert.equal(existsSync(join(syncEnv.managedStateHome, WINDOWS_PATH_MARKER_FILE)), true);
    assert.equal(
      wrapperDirectory(syncEnv, "win32"),
      join(home, "local-app-data", "Programs", "Agents", "bin"),
    );

    const [codex] = wrapperDestinations(syncEnv, "win32");
    assert.ok(codex);
    const updated = { ...codex, content: `${codex.content}rem updated\r\n` };
    assert.deepEqual(reconcileWrapperFiles(syncEnv, [updated], "win32").owned, [updated.path]);
    assert.equal(readFileSync(updated.path, "utf8"), updated.content);
  });
});
