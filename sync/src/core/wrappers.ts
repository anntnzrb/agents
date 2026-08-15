import fs from "node:fs";
import path from "node:path";

import type { HostPlatform, Harness, SyncEnv } from "./harness.ts";
import { isErrno, panicMessage } from "@runtime/errors.ts";

export const UNIX_WRAPPER_DIR = [".local", "bin"] as const;
export const WINDOWS_WRAPPER_DIR = ["Programs", "Agents", "bin"] as const;
export const WRAPPER_STATE_FILE = "wrappers.json";
export const WINDOWS_PATH_MARKER_FILE = "windows-path-added";
export const WRAPPER_MARKER = "agents-managed-wrapper:v1";

interface WrapperState {
  readonly version: 1;
  readonly entries: readonly string[];
}

export interface WrapperDestination {
  readonly harness: Harness;
  readonly path: string;
  readonly content: string;
}

export interface WrapperReconcileResult {
  readonly owned: readonly string[];
  readonly conflicts: readonly string[];
  readonly removed: readonly string[];
}

export interface WrapperRuntime {
  readonly platform?: HostPlatform;
  readonly writeWindowsPath?: (directory: string) => boolean;
}

export function wrapperDirectory(
  syncEnv: Pick<SyncEnv, "home" | "platform" | "localAppData">,
  platform: HostPlatform = syncEnv.platform,
): string {
  if (platform === "win32") {
    const localAppData =
      syncEnv.localAppData ?? path.join(syncEnv.home, "AppData", "Local");
    return path.join(localAppData, ...WINDOWS_WRAPPER_DIR);
  }
  return path.join(syncEnv.home, ...UNIX_WRAPPER_DIR);
}

export function wrapperPath(
  syncEnv: Pick<SyncEnv, "home" | "platform" | "localAppData">,
  harness: Harness,
  platform: HostPlatform = syncEnv.platform,
): string {
  const suffix = platform === "win32" ? ".cmd" : "";
  return path.join(wrapperDirectory(syncEnv, platform), `${harness.sourceName}${suffix}`);
}

export function wrapperDestinations(
  syncEnv: Pick<SyncEnv, "home" | "platform" | "localAppData" | "harnesses">,
  platform: HostPlatform = syncEnv.platform,
): readonly WrapperDestination[] {
  return syncEnv.harnesses.map((harness) => {
    const destination = wrapperPath(syncEnv, harness, platform);
    return {
      harness,
      path: destination,
      content: renderWrapper(syncEnv, harness, platform),
    };
  });
}

export function renderWrapper(
  syncEnv: Pick<SyncEnv, "home">,
  harness: Harness,
  platform: HostPlatform,
): string {
  const syncScript = path.join(
    syncEnv.home,
    ".config",
    "agents",
    "sync",
    "src",
    "cli.ts",
  );
  if (platform === "win32") {
    return [
      "@echo off",
      `rem ${WRAPPER_MARKER}`,
      `bun ${windowsQuote(syncScript)} launch ${harness.sourceName} -- %*`,
      "exit /b %ERRORLEVEL%",
      "",
    ].join("\r\n");
  }

  return [
    "#!/bin/sh",
    `# ${WRAPPER_MARKER}`,
    "set -eu",
    `exec bun ${shellQuote(syncScript)} launch ${shellQuote(harness.sourceName)} -- \"$@\"`,
    "",
  ].join("\n");
}

export function reconcileWrappers(
  syncEnv: SyncEnv,
  runtime: WrapperRuntime = {},
): boolean {
  try {
    const platform = runtime.platform ?? syncEnv.platform;
    const desired = wrapperDestinations(syncEnv, platform);
    const result = reconcileWrapperFiles(syncEnv, desired, platform);
    if (result.conflicts.length > 0) {
      for (const conflict of result.conflicts) {
        console.error(`sync: warning: preserving unmanaged wrapper conflict: ${conflict}`);
      }
    }
    if (platform === "win32") {
      const addPath =
        runtime.writeWindowsPath ?? ((directory) => ensureWindowsUserPath(syncEnv, directory));
      const markerPath = path.join(
        syncEnv.managedStateHome,
        WINDOWS_PATH_MARKER_FILE,
      );
      if (!exists(markerPath)) {
        if (!addPath(wrapperDirectory(syncEnv, platform))) {
          return false;
        }
        fs.mkdirSync(path.dirname(markerPath), { recursive: true });
        fs.writeFileSync(markerPath, `${wrapperDirectory(syncEnv, platform)}\n`, "utf8");
      }
    }
    return true;
  } catch (error) {
    console.error(`sync: wrapper reconciliation failed: ${panicMessage(error)}`);
    return false;
  }
}

export function reconcileWrapperFiles(
  syncEnv: Pick<SyncEnv, "managedStateHome"> &
    Partial<Pick<SyncEnv, "home" | "platform" | "localAppData">>,
  desired: readonly WrapperDestination[],
  platform: HostPlatform,
): WrapperReconcileResult {
  const statePath = path.join(syncEnv.managedStateHome, WRAPPER_STATE_FILE);
  const previous = readWrapperState(statePath);
  const desiredByPath = new Map(desired.map((entry) => [entry.path, entry]));
  const allowedDirectories = new Set(
    desired.map((entry) => path.resolve(path.dirname(entry.path))),
  );
  if (syncEnv.home && syncEnv.platform) {
    allowedDirectories.add(
      path.resolve(
        wrapperDirectory(
          syncEnv as Pick<SyncEnv, "home" | "platform" | "localAppData">,
          platform,
        ),
      ),
    );
  }
  const owned: string[] = [];
  const conflicts: string[] = [];
  const removed: string[] = [];

  for (const oldPath of previous.entries) {
    if (desiredByPath.has(oldPath)) {
      continue;
    }
    if (!allowedDirectories.has(path.resolve(path.dirname(oldPath)))) {
      conflicts.push(oldPath);
      continue;
    }
    if (isManagedWrapper(oldPath)) {
      removeWrapper(oldPath);
      removed.push(oldPath);
    } else {
      conflicts.push(oldPath);
    }
  }

  for (const entry of desired) {
    const status = writeManagedWrapper(entry.path, entry.content, platform);
    if (status === "owned") {
      owned.push(entry.path);
    } else {
      conflicts.push(entry.path);
    }
  }

  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  writeWrapperState(
    statePath,
    {
      version: 1,
      entries: [...new Set(owned)].sort(),
    },
    platform,
  );

  return { owned, conflicts: [...new Set(conflicts)], removed };
}

export function readWrapperState(statePath: string): WrapperState {
  let content: string;
  try {
    content = fs.readFileSync(statePath, "utf8");
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return { version: 1, entries: [] };
    }
    throw new Error(`read ${statePath} (${panicMessage(error)})`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch (error) {
    console.error(`sync: warning: wrapper state parse failed, ignoring ${statePath} (${panicMessage(error)})`);
    return { version: 1, entries: [] };
  }

  if (!isRecord(parsed) || parsed.version !== 1 || !Array.isArray(parsed.entries)) {
    console.error(`sync: warning: wrapper state parse failed, ignoring ${statePath} (invalid shape)`);
    return { version: 1, entries: [] };
  }

  const entries = parsed.entries.filter(
    (entry): entry is string => typeof entry === "string" && path.isAbsolute(entry),
  );
  return { version: 1, entries: [...new Set(entries)].sort() };
}

function writeWrapperState(
  statePath: string,
  state: WrapperState,
  platform: HostPlatform,
): void {
  const content = `${JSON.stringify(state, null, 2)}\n`;
  try {
    if (fs.readFileSync(statePath, "utf8") === content) {
      return;
    }
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw new Error(`read ${statePath} (${panicMessage(error)})`);
    }
  }
  const tempPath = `${statePath}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, content, "utf8");
  try {
    if (platform === "win32") {
      fs.rmSync(statePath, { force: true });
    }
    fs.renameSync(tempPath, statePath);
  } catch (error) {
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {
      // Best effort cleanup; preserve the original replacement error.
    }
    throw new Error(`replace ${statePath} (${panicMessage(error)})`);
  }
}

function writeManagedWrapper(
  targetPath: string,
  content: string,
  platform: HostPlatform,
): "owned" | "conflict" {
  try {
    const metadata = fs.lstatSync(targetPath);
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      return "conflict";
    }
    if (!isManagedWrapper(targetPath)) {
      return "conflict";
    }
    if (fs.readFileSync(targetPath, "utf8") === content) {
      return "owned";
    }
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw new Error(`inspect wrapper ${targetPath} (${panicMessage(error)})`);
    }
  }

  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  const tempPath = `${targetPath}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, content, "utf8");
  if (process.platform !== "win32" && !targetPath.endsWith(".cmd")) {
    fs.chmodSync(tempPath, 0o755);
  }
  try {
    if (platform === "win32") {
      fs.rmSync(targetPath, { force: true });
    }
    fs.renameSync(tempPath, targetPath);
  } catch (error) {
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {
      // Best effort cleanup; preserve the original replacement error.
    }
    throw new Error(`replace wrapper ${targetPath} (${panicMessage(error)})`);
  }
  return "owned";
}

function isManagedWrapper(targetPath: string): boolean {
  try {
    const metadata = fs.lstatSync(targetPath);
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      return false;
    }
    return fs.readFileSync(targetPath, "utf8").includes(WRAPPER_MARKER);
  } catch {
    return false;
  }
}

function removeWrapper(targetPath: string): void {
  try {
    fs.rmSync(targetPath, { force: false });
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw new Error(`remove wrapper ${targetPath} (${panicMessage(error)})`);
    }
  }
}

export function ensureWindowsUserPath(syncEnv: SyncEnv, directory: string): boolean {
  const markerPath = path.join(
    syncEnv.managedStateHome,
    WINDOWS_PATH_MARKER_FILE,
  );
  if (exists(markerPath)) {
    return true;
  }

  const currentPath = process.env.PATH ?? "";
  const normalizedDirectory = path.normalize(directory).toLowerCase();
  const hasDirectory = currentPath
    .split(path.delimiter)
    .some((entry) => path.normalize(entry).toLowerCase() === normalizedDirectory);
  if (!hasDirectory) {
    const command = [
      "powershell.exe",
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      "$old=[Environment]::GetEnvironmentVariable('Path','User');$parts=@();if($old){$parts=$old -split ';'};if($parts -notcontains $args[0]){$parts += $args[0];[Environment]::SetEnvironmentVariable('Path',($parts -join ';'),'User')}",
      directory,
    ];
    const result = Bun.spawnSync(command, { stdout: "ignore", stderr: "pipe" });
    if (!result.success) {
      console.error(`sync: failed to add wrapper directory to Windows user PATH: ${result.stderr?.toString().trim() ?? "unknown error"}`);
      return false;
    }
  }

  fs.mkdirSync(path.dirname(markerPath), { recursive: true });
  fs.writeFileSync(markerPath, `${directory}\n`, "utf8");
  return true;
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function windowsQuote(value: string): string {
  return `"${value.replaceAll("\"", "\\\"")}"`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exists(targetPath: string): boolean {
  try {
    fs.accessSync(targetPath);
    return true;
  } catch {
    return false;
  }
}
