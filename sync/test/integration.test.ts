import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, resolve, sep } from "node:path";
import { tmpdir } from "node:os";
import { setDefaultTimeout, test } from "bun:test";

const SYNC_ROOT = resolve(import.meta.dir, "..");
const REPO_ROOT = resolve(SYNC_ROOT, "..");
const TS_SYNC = resolve(SYNC_ROOT, "src/cli.ts");

setDefaultTimeout(30_000);

type RunResult = {
  exitCode: number;
  stdout: string;
  stderr: string;
};

type SnapshotEntry = {
  path: string;
  kind: "file" | "dir" | "symlink";
  content?: string;
};

test("integration_happy_path_matches_expected_outputs", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
    assert.equal(existsSync(join(home, ".codex", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".claude", "CLAUDE.md")), true);
    assert.equal(existsSync(join(home, ".claude", "AGENTS.md")), false);
    assert.equal(existsSync(join(home, ".config", "opencode", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".pi", "agent", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "AGENTS.md")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "config.yml")), true);
    assert.equal(existsSync(join(home, ".omp", "agent", "skills", "skill.txt")), true);
    assert.equal(existsSync(join(home, ".mcporter", "mcporter.json")), true);
    assert.equal(existsSync(join(home, ".pi", "agent", "auth.json")), true);
  });
});

test("integration_missing_sources_remain_non_fatal", () => {
  withTempDir((root) => {
    const home = join(root, "ts-home");
    mkdirSync(join(home, ".config", "agents", "assets"), { recursive: true });
    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
  });
});

test("integration_package_bootstrap_patches_settings_and_cache_paths", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const sourceRepo = join(root, "repos", "source-pkg");
    const buildRepo = join(root, "repos", "build-pkg");
    setupPackageRepos(sourceRepo, buildRepo);
    writeFileSync(
      join(home, ".config", "agents", "tools", "pi", "agent", "packages.json"),
      `${JSON.stringify({ packages: [sourceRepo, buildRepo] }, null, 2)}\n`,
    );

    const result = runSyncProcess(home);

    assert.equal(result.exitCode, 0, result.stderr || result.stdout);
    const settings = readFileSync(join(home, ".pi", "agent", "settings.json"), "utf8");
    assert.equal(settings.includes("source-pkg"), true);
    assert.equal(settings.includes("build-pkg"), true);
    const cacheSnapshot = snapshotSelected(join(home, ".local", "share", "agents", "pi-packages"));
    assert.equal(cacheSnapshot.some((entry) => entry.path.includes("source-pkg")), true);
    assert.equal(cacheSnapshot.some((entry) => entry.path.includes("build-pkg")), true);
  });
});

test("integration_invalid_package_json_fails_package_bootstrap", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const badRepo = join(root, "repos", "bad-pkg");
    mkdirSync(badRepo, { recursive: true });
    writeFileSync(join(badRepo, "package.json"), "{not valid json");
    initGitRepo(badRepo);

    writeFileSync(
      join(home, ".config", "agents", "tools", "pi", "agent", "packages.json"),
      `${JSON.stringify({ packages: [badRepo] }, null, 2)}\n`,
    );

    const result = runSyncProcess(home);

    assert.notEqual(result.exitCode, 0);
    assert.equal(result.stderr.includes("package bootstrap failed for"), true);
  });
});

test("integration_repeated_runs_remain_idempotent", () => {
  withTempDir((root) => {
    const home = makeFixture(root);
    const first = runSyncProcess(home);
    const snapshotAfterFirst = snapshotHome(home);
    const second = runSyncProcess(home);
    const snapshotAfterSecond = snapshotHome(home);

    assert.equal(first.exitCode, 0, first.stderr || first.stdout);
    assert.equal(second.exitCode, 0, second.stderr || second.stdout);
    assert.deepEqual(snapshotAfterFirst, snapshotAfterSecond);
  });
});

function withTempDir<T>(fn: (root: string) => T): T {
  const root = mkdtempSync(join(tmpdir(), "agents-integration-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function makeFixture(root: string): string {
  const home = join(root, "ts-home");
  mkdirSync(join(home, ".config", "agents", "assets"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "codex"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "omp", "agent"), { recursive: true });
  mkdirSync(join(home, ".config", "agents", "tools", "pi", "agent"), { recursive: true });
  mkdirSync(join(home, ".pi", "agent"), { recursive: true });
  mkdirSync(join(home, ".omp", "agent"), { recursive: true });
  mkdirSync(join(home, ".omp", "agent", "logs"), { recursive: true });
  mkdirSync(join(home, ".codex"), { recursive: true });
  mkdirSync(join(home, ".claude"), { recursive: true });
  mkdirSync(join(home, ".config", "opencode"), { recursive: true });
  mkdirSync(join(home, ".mcporter"), { recursive: true });

  writeFixtureFiles(home);
  return home;
}

function writeFixtureFiles(home: string): void {
  writeFileSync(join(home, ".config", "agents", "assets", "AGENTS.md"), "agent-instructions");
  writeFileSync(join(home, ".config", "agents", "assets", "mcporter.jsonc"), '{"x":1}');
  mkdirSync(join(home, ".config", "agents", "assets", "skills"), { recursive: true });
  writeFileSync(join(home, ".config", "agents", "assets", "skills", "skill.txt"), "skill-content");
  writeFileSync(join(home, ".config", "agents", "tools", "codex", "config.toml"), "codex = true");
  writeFileSync(
    join(home, ".config", "agents", "tools", "omp", "agent", "config.yml"),
    "theme:\n  dark: graphite\n",
  );
  writeFileSync(join(home, ".pi", "agent", "auth.json"), '{"token":1}');
  writeFileSync(join(home, ".pi", "agent", "settings.json"), "{}\n");
  writeFileSync(join(home, ".omp", "agent", "logs", "keep.txt"), "keep-me");
}

function setupPackageRepos(sourceRepo: string, buildRepo: string): void {
  mkdirSync(join(sourceRepo, "src"), { recursive: true });
  mkdirSync(join(buildRepo, "src"), { recursive: true });
  writeFileSync(
    join(sourceRepo, "package.json"),
    `{
  "pi": {
    "extensions": ["./src/index.ts"]
  }
}
`,
  );
  writeFileSync(join(sourceRepo, "src", "index.ts"), "export default {}\n");
  writeFileSync(
    join(buildRepo, "package.json"),
    `{
  "scripts": {
    "build": "bun run build.ts"
  },
  "pi": {
    "extensions": ["./dist/index.js"]
  }
}
`,
  );
  writeFileSync(
    join(buildRepo, "build.ts"),
    `import { mkdirSync, writeFileSync } from "node:fs";
mkdirSync("dist", { recursive: true });
writeFileSync("dist/index.js", "export default {}\\n");
`,
  );
  initGitRepo(sourceRepo);
  initGitRepo(buildRepo);
}

function initGitRepo(repoPath: string): void {
  const commands = [
    ["git", "init"],
    ["git", "config", "user.name", "Test User"],
    ["git", "config", "user.email", "test@example.com"],
    ["git", "add", "."],
    ["git", "commit", "-m", "init"],
  ];
  for (const command of commands) {
    const [cmd, ...args] = command;
    const result = spawnSync(cmd!, args, {
      cwd: repoPath,
      encoding: "utf8",
      stdio: "pipe",
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
  }
}

function runSyncProcess(home: string): RunResult {
  const result = spawnSync("bun", [TS_SYNC], {
    cwd: SYNC_ROOT,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: home,
      PATH: process.env.PATH ?? "",
    },
    stdio: "pipe",
  });

  return {
    exitCode: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

function snapshotHome(home: string): SnapshotEntry[] {
  const roots = [
    ".claude",
    ".codex",
    ".config/opencode",
    ".pi",
    ".omp",
    ".mcporter",
    ".local/share/agents/sync-managed",
    ".local/share/agents/pi-packages",
  ];
  const entries: SnapshotEntry[] = [];
  for (const root of roots) {
    const absolute = join(home, root);
    if (existsSync(absolute)) {
      walk(absolute, root, entries);
    }
  }
  return entries.filter((entry) => !entry.path.includes("/sync.lock"));
}

function snapshotSelected(root: string): SnapshotEntry[] {
  const entries: SnapshotEntry[] = [];
  if (existsSync(root)) {
    walk(root, "", entries);
  }
  return entries.filter((entry) => !entry.path.includes("/.git") && !entry.path.includes("/node_modules"));
}

function walk(absolute: string, relative: string, out: SnapshotEntry[]): void {
  const stat = lstatSync(absolute);
  if (stat.isSymbolicLink()) {
    out.push({ path: normalizePath(relative), kind: "symlink" });
    return;
  }
  if (stat.isDirectory()) {
    out.push({ path: normalizePath(relative), kind: "dir" });
    const children = readdirSync(absolute).sort();
    for (const child of children) {
      walk(join(absolute, child), relative ? `${relative}/${child}` : child, out);
    }
    return;
  }
  out.push({
    path: normalizePath(relative),
    kind: "file",
    content: readFileSync(absolute, "utf8"),
  });
}

const normalizePath = (path: string): string => path.split(sep).join("/");
