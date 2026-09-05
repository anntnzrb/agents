import { afterAll } from "bun:test";
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join, resolve } from "node:path";

/**
 * Tests redirect HOME to a throwaway directory so sync writes nowhere real.
 * Cache variables redirect to an isolated temporary cache directory to prevent
 * test processes from writing to real user directories or competing for locks.
 */
const SHARED_CACHE_DIR = mkdtempSync(join(tmpdir(), "agents-test-cache-"));

export const sharedToolCacheEnv: Readonly<Record<string, string>> = {
  UV_CACHE_DIR: process.env["UV_CACHE_DIR"] ?? join(SHARED_CACHE_DIR, "uv"),
  UV_PYTHON_INSTALL_DIR:
    process.env["UV_PYTHON_INSTALL_DIR"] ?? join(SHARED_CACHE_DIR, "uv-python"),
  BUN_INSTALL_CACHE_DIR:
    process.env["BUN_INSTALL_CACHE_DIR"] ?? join(SHARED_CACHE_DIR, "bun-install"),
};

const SYNC_ROOT = resolve(import.meta.dir, "..", "..");
const RUNTIME_MANIFESTS = ["package.json", "tsconfig.json", "bun.lock"] as const;

/** Captured at import, before any test can stub a tool onto PATH. */
export const PRISTINE_PATH = process.env["PATH"] ?? "";

/**
 * Every test that runs sync against a fresh HOME hits the SyncRuntimeInstall
 * job, which stages the runtime and shells out to `bun install` (~0.9s each
 * even cache-warm, and its 1s floor in jobs.ts races short install timeouts).
 * The release id is a content hash of src/ plus the three manifests, so one
 * release built from this repo is valid for every fixture that copies those
 * same sources. Build it once per test process by letting the real CLI
 * produce it — deriving the id here would duplicate hashing that lives in
 * jobs.ts — then clone it into each fixture so the job short-circuits at its
 * isCompleteRelease check.
 */
interface SharedRelease {
  /** Directory of the prebuilt release, named by its content-hash id. */
  readonly dir: string;
  /** Enclosing throwaway HOME; removed wholesale at teardown. */
  readonly templateHome: string;
  readonly id: string;
}

let cachedRelease: SharedRelease | undefined;

// The template outlives every test in the file, so it cannot be tied to a
// per-test temp dir. bun's test runner never fires process "exit" handlers,
// so release it from the suite-level teardown hook. Registered at module
// scope: bun only accepts lifecycle hooks during module evaluation.
afterAll(() => {
  const release = cachedRelease;
  cachedRelease = undefined;
  if (release !== undefined) {
    rmSync(release.templateHome, { recursive: true, force: true });
  }
  rmSync(SHARED_CACHE_DIR, { recursive: true, force: true });
});

function buildSharedRelease(): SharedRelease {
  const templateHome = mkdtempSync(join(tmpdir(), "agents-shared-release-"));
  const source = join(templateHome, ".config", "agents", "sync");
  mkdirSync(source, { recursive: true });
  cpSync(join(SYNC_ROOT, "src"), join(source, "src"), { recursive: true });
  for (const file of RUNTIME_MANIFESTS) {
    copyFileSync(join(SYNC_ROOT, file), join(source, file));
  }
  // Sync aborts on a missing deployment manifest before it reaches the
  // runtime install job, so the template needs a minimal one. The client
  // endpoint is deliberately dead: this run exists only to produce the
  // release directory, not to reach any service.
  const tools = join(templateHome, ".config", "agents", "tools", "cliproxyapi");
  mkdirSync(tools, { recursive: true });
  writeFileSync(
    join(tools, "deployment.json"),
    `${JSON.stringify({
      server: { hostname: hostname() },
      listen: { host: "100.64.0.42", port: 8317 },
      client: { baseUrl: "http://127.0.0.1:1/v1" },
    })}\n`,
  );

  const built = Bun.spawnSync([process.execPath, join(SYNC_ROOT, "src", "cli.ts")], {
    cwd: SYNC_ROOT,
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
    env: {
      ...Bun.env,
      HOME: templateHome,
      XDG_CACHE_HOME: join(templateHome, ".cache"),
      // Tests that stub `uv` mutate the shared process.env["PATH"]; building
      // the template must not inherit whichever fake happens to be installed.
      PATH: PRISTINE_PATH,
      ...sharedToolCacheEnv,
    },
  });

  const releasesRoot = join(templateHome, ".local", "share", "agents", "sync-releases");
  const id = existsSync(releasesRoot)
    ? readdirSync(releasesRoot, { withFileTypes: true }).find(
        (entry) => entry.isDirectory() && !entry.name.startsWith(".stage-"),
      )?.name
    : undefined;
  if (id === undefined) {
    throw new Error(
      `shared test release was not produced: ${built.stderr.toString() || built.stdout.toString()}`,
    );
  }
  return { dir: join(releasesRoot, id), templateHome, id };
}

/**
 * Seed `home` with the prebuilt runtime release so SyncRuntimeInstall reuses
 * it instead of running `bun install`. Mirrors the layout plan.ts derives:
 * <home>/.local/share/agents/sync-releases/<releaseId>.
 */
export function seedRuntimeRelease(home: string): void {
  cachedRelease ??= buildSharedRelease();
  const release = cachedRelease;
  const target = join(home, ".local", "share", "agents", "sync-releases", release.id);
  mkdirSync(target, { recursive: true });
  cpSync(join(release.dir, "src"), join(target, "src"), { recursive: true });
  for (const file of RUNTIME_MANIFESTS) {
    copyFileSync(join(release.dir, file), join(target, file));
  }
  // node_modules dominates the release (~59MB); copying it per test costs as
  // much as the `bun install` this avoids. It is read-only for these tests,
  // and isCompleteRelease stats through the link, so share one copy.
  symlinkSync(join(release.dir, "node_modules"), join(target, "node_modules"), "dir");
}
