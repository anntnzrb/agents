import fs from "node:fs";
import path from "node:path";
import { panicMessage } from "@runtime/errors.ts";
import { Schema } from "effect";
import {
  CLI_PROXY_SOURCE_DIR,
  type CliProxyDeployment,
  cliProxyModelsUrl,
} from "./cliproxy-deployment.ts";
import type { SyncEnv } from "./harness.ts";

const TOOL_NAME = "cliproxyapi";
const RELEASE_FILE = "release.json";
const COMPONENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const REPOSITORY_PATTERN = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;

const ReleaseAssetSchema = Schema.Struct({
  name: Schema.NonEmptyString.pipe(
    Schema.check(
      Schema.makeFilter((s: string) =>
        COMPONENT_PATTERN.test(s) ? undefined : "invalid component name",
      ),
    ),
  ),
  sha256: Schema.NonEmptyString.pipe(
    Schema.check(
      Schema.makeFilter((s: string) => (SHA256_PATTERN.test(s) ? undefined : "invalid sha256")),
    ),
  ),
});

const ReleaseManifestSchema = Schema.Struct({
  repository: Schema.NonEmptyString.pipe(
    Schema.check(
      Schema.makeFilter((s: string) =>
        REPOSITORY_PATTERN.test(s) ? undefined : "invalid repository",
      ),
    ),
  ),
  version: Schema.NonEmptyString.pipe(
    Schema.check(
      Schema.makeFilter((s: string) => (COMPONENT_PATTERN.test(s) ? undefined : "invalid version")),
    ),
  ),
  binary: Schema.NonEmptyString.pipe(
    Schema.check(
      Schema.makeFilter((s: string) => (COMPONENT_PATTERN.test(s) ? undefined : "invalid binary")),
    ),
  ),
  assets: Schema.Record(Schema.String, ReleaseAssetSchema),
});

type ReleaseManifest = typeof ReleaseManifestSchema.Type;

type FetchImplementation = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface PreparedManagedTool {
  readonly name: string;
  readonly command: string;
  readonly executable: string;
  readonly version: string;
  readonly configPath: string;
}

export interface ManagedToolRuntime {
  readonly arch?: NodeJS.Architecture;
  readonly cacheHome?: string;
  readonly download?: (url: string, destination: string, timeoutMs: number) => Promise<void>;
  readonly extract?: (
    archive: string,
    destination: string,
    entryName: string,
    timeoutMs: number,
  ) => Promise<void>;
}

export async function prepareManagedTools(
  syncEnv: SyncEnv,
  runtime: ManagedToolRuntime = {},
): Promise<readonly PreparedManagedTool[]> {
  const manifestPath = path.join(syncEnv.ssotHome, CLI_PROXY_SOURCE_DIR, RELEASE_FILE);
  if (!fs.existsSync(manifestPath)) {
    return [];
  }
  return [await prepareCliProxy(syncEnv, manifestPath, runtime)];
}

export async function isCliProxyRunning(
  deployment: CliProxyDeployment,
  timeoutMs = 500,
  fetchImpl: FetchImplementation = fetch,
): Promise<boolean> {
  try {
    await fetchImpl(cliProxyModelsUrl(deployment), {
      signal: AbortSignal.timeout(timeoutMs),
    });
    return true;
  } catch {
    return false;
  }
}

async function prepareCliProxy(
  syncEnv: SyncEnv,
  manifestPath: string,
  runtime: ManagedToolRuntime,
): Promise<PreparedManagedTool> {
  const manifest = readManifest(manifestPath);
  const arch = supportedArch(runtime.arch ?? process.arch);
  const platformKey = `${syncEnv.platform}-${arch}`;
  const asset = manifest.assets[platformKey];
  if (!asset) {
    throw new Error(`CLIProxyAPI has no release asset for ${platformKey}`);
  }

  const executableName = manifest.binary;
  const cacheHome =
    runtime.cacheHome ??
    Bun.env["XDG_CACHE_HOME"] ??
    process.env["XDG_CACHE_HOME"] ??
    path.join(syncEnv.home, ".cache");
  const installDir = path.join(
    cacheHome,
    "github-tools",
    TOOL_NAME,
    "versions",
    manifest.version,
    platformKey,
  );
  const executable = path.join(installDir, executableName);
  const receiptPath = path.join(installDir, "receipt.json");
  const receipt = `${JSON.stringify(
    {
      repository: manifest.repository,
      version: manifest.version,
      asset: asset.name,
      sha256: asset.sha256,
    },
    null,
    2,
  )}\n`;

  if (!installedToolMatches(executable, receiptPath, receipt)) {
    fs.rmSync(installDir, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(installDir), { recursive: true });
    const stageDir = fs.mkdtempSync(path.join(path.dirname(installDir), ".stage."));
    try {
      const archivePath = path.join(stageDir, asset.name);
      const url = `https://github.com/${manifest.repository}/releases/download/v${manifest.version}/${asset.name}`;
      await (runtime.download ?? downloadRelease)(url, archivePath, syncEnv.installTimeoutMs);
      verifyChecksum(archivePath, asset.sha256);
      await (runtime.extract ?? extractRelease)(
        archivePath,
        stageDir,
        executableName,
        syncEnv.installTimeoutMs,
      );
      fs.rmSync(archivePath, { force: true });
      if (!fs.statSync(path.join(stageDir, executableName)).isFile()) {
        throw new Error(`CLIProxyAPI archive is missing ${executableName}`);
      }
      fs.chmodSync(path.join(stageDir, executableName), 0o755);
      fs.writeFileSync(path.join(stageDir, "receipt.json"), receipt, "utf8");
      fs.renameSync(stageDir, installDir);
    } catch (error) {
      fs.rmSync(stageDir, { recursive: true, force: true });
      throw new Error(`install CLIProxyAPI ${manifest.version} (${panicMessage(error)})`, {
        cause: error,
      });
    }
  }

  return {
    name: TOOL_NAME,
    command: manifest.binary,
    executable,
    version: manifest.version,
    configPath: path.join(syncEnv.home, ".cli-proxy-api", "config.yaml"),
  };
}

function readManifest(manifestPath: string): ReleaseManifest {
  let parsed: unknown;
  try {
    parsed = Bun.JSONC.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`parse ${manifestPath} (${panicMessage(error)})`, { cause: error });
  }
  try {
    return Schema.decodeUnknownSync(ReleaseManifestSchema)(parsed);
  } catch (error) {
    throw new Error(`invalid release manifest: ${manifestPath}`, { cause: error });
  }
}

async function downloadRelease(url: string, destination: string, timeoutMs: number): Promise<void> {
  const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  if (!response.ok) {
    throw new Error(`download failed with HTTP ${response.status}`);
  }
  await Bun.write(destination, await response.arrayBuffer());
}

async function extractRelease(
  archive: string,
  destination: string,
  entryName: string,
  timeoutMs: number,
): Promise<void> {
  const tar = Bun.which("tar");
  if (!tar) {
    throw new Error("missing tar executable");
  }
  const signal = AbortSignal.timeout(timeoutMs);
  const process = Bun.spawn([tar, "-xf", archive, "-C", destination, entryName], {
    signal,
    killSignal: "SIGKILL",
    stdin: "ignore",
    stdout: "ignore",
    stderr: "pipe",
  });
  const [stderr, exitCode] = await Promise.all([
    new Response(process.stderr).text().catch(() => ""),
    process.exited,
  ]);
  if (signal.aborted) {
    throw new Error("archive extraction timed out");
  }
  if (exitCode !== 0) {
    throw new Error(`archive extraction failed: ${stderr.trim() || "unknown error"}`);
  }
}

function verifyChecksum(archive: string, expected: string): void {
  const actual = new Bun.CryptoHasher("sha256").update(fs.readFileSync(archive)).digest("hex");
  if (actual !== expected) {
    throw new Error(`checksum mismatch for ${path.basename(archive)}`);
  }
}

function installedToolMatches(executable: string, receiptPath: string, receipt: string): boolean {
  try {
    const metadata = fs.statSync(executable);
    return (
      metadata.isFile() &&
      (metadata.mode & 0o111) !== 0 &&
      fs.readFileSync(receiptPath, "utf8") === receipt
    );
  } catch {
    return false;
  }
}

function supportedArch(arch: NodeJS.Architecture): "arm64" | "x64" {
  if (arch === "arm64" || arch === "x64") {
    return arch;
  }
  throw new Error(`unsupported architecture: ${arch}`);
}
