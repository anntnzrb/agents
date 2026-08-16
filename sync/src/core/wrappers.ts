import fs from "node:fs";
import path from "node:path";
import { isErrno, panicMessage } from "@runtime/errors.ts";
import type { Harness, SyncEnv } from "./harness.ts";
import type { PreparedManagedTool } from "./managed-tools.ts";

export const UNIX_WRAPPER_DIR = [".local", "bin"] as const;
export const WRAPPER_STATE_FILE = "wrappers.json";
export const WRAPPER_MARKER = "agents-managed-wrapper:v1";

interface WrapperState {
  readonly version: 1;
  readonly entries: readonly string[];
}

export interface WrapperDestination {
  readonly path: string;
  readonly content: string;
}

export interface HarnessWrapperDestination extends WrapperDestination {
  readonly harness: Harness;
}

export interface WrapperReconcileResult {
  readonly owned: readonly string[];
  readonly conflicts: readonly string[];
  readonly removed: readonly string[];
}

export interface WrapperRuntime {
  readonly additionalDestinations?: readonly WrapperDestination[];
}

export function wrapperDirectory(syncEnv: Pick<SyncEnv, "home">): string {
  return path.join(syncEnv.home, ...UNIX_WRAPPER_DIR);
}

export function wrapperPath(syncEnv: Pick<SyncEnv, "home">, harness: Harness): string {
  return path.join(wrapperDirectory(syncEnv), harness.launcher.bin);
}

export function wrapperDestinations(
  syncEnv: Pick<SyncEnv, "home" | "runtimeHome" | "harnesses">,
): readonly HarnessWrapperDestination[] {
  return syncEnv.harnesses.map((harness) => {
    const destination = wrapperPath(syncEnv, harness);
    return {
      harness,
      path: destination,
      content: renderWrapper(syncEnv, harness),
    };
  });
}

export function renderWrapper(syncEnv: Pick<SyncEnv, "runtimeHome">, harness: Harness): string {
  const syncScript = path.join(syncEnv.runtimeHome, "sync", "src", "cli.ts");
  const defaultArgs = harness.launcher.defaultArgs.map(shellQuote).join(" ");
  return [
    "#!/bin/sh",
    `# ${WRAPPER_MARKER}`,
    "set -eu",
    `if [ ! -f ${shellQuote(syncScript)} ]; then`,
    "  echo 'agents: sync runtime is missing; run sync from the agents repository' >&2",
    "  exit 127",
    "fi",
    `exec bun ${shellQuote(syncScript)} launch ${shellQuote(harness.sourceName)} --${defaultArgs ? ` ${defaultArgs}` : ""} "$@"`,
    "",
  ].join("\n");
}

export function managedToolWrapperDestination(
  syncEnv: Pick<SyncEnv, "home">,
  tool: PreparedManagedTool,
): WrapperDestination {
  return {
    path: path.join(wrapperDirectory(syncEnv), tool.command),
    content: renderManagedToolWrapper(tool),
  };
}

function renderManagedToolWrapper(tool: PreparedManagedTool): string {
  return [
    "#!/bin/sh",
    `# ${WRAPPER_MARKER}`,
    "set -eu",
    `exec ${shellQuote(tool.executable)} --config ${shellQuote(tool.configPath)} "$@"`,
    "",
  ].join("\n");
}

export function reconcileWrappers(syncEnv: SyncEnv, runtime: WrapperRuntime = {}): boolean {
  try {
    const desired = [...wrapperDestinations(syncEnv), ...(runtime.additionalDestinations ?? [])];
    const result = reconcileWrapperFiles(syncEnv, desired);
    if (result.conflicts.length > 0) {
      for (const conflict of result.conflicts) {
        console.error(`sync: warning: preserving unmanaged wrapper conflict: ${conflict}`);
      }
    }
    return true;
  } catch (error) {
    console.error(`sync: wrapper reconciliation failed: ${panicMessage(error)}`);
    return false;
  }
}

export function reconcileWrapperFiles(
  syncEnv: Pick<SyncEnv, "managedStateHome"> & Partial<Pick<SyncEnv, "home">>,
  desired: readonly WrapperDestination[],
): WrapperReconcileResult {
  const statePath = path.join(syncEnv.managedStateHome, WRAPPER_STATE_FILE);
  const previous = readWrapperState(statePath);
  const desiredByPath = new Map(desired.map((entry) => [entry.path, entry]));
  const allowedDirectories = new Set(
    desired.map((entry) => path.resolve(path.dirname(entry.path))),
  );
  if (syncEnv.home) {
    allowedDirectories.add(path.resolve(wrapperDirectory({ home: syncEnv.home })));
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
    const status = writeManagedWrapper(entry.path, entry.content);
    if (status === "owned") {
      owned.push(entry.path);
    } else {
      conflicts.push(entry.path);
    }
  }

  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  writeWrapperState(statePath, {
    version: 1,
    entries: [...new Set(owned)].toSorted(),
  });

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
    throw new Error(`read ${statePath} (${panicMessage(error)})`, { cause: error });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch (error) {
    console.error(
      `sync: warning: wrapper state parse failed, ignoring ${statePath} (${panicMessage(error)})`,
    );
    return { version: 1, entries: [] };
  }

  if (!isRecord(parsed) || parsed["version"] !== 1 || !Array.isArray(parsed["entries"])) {
    console.error(
      `sync: warning: wrapper state parse failed, ignoring ${statePath} (invalid shape)`,
    );
    return { version: 1, entries: [] };
  }

  const entries = parsed["entries"].filter(
    (entry): entry is string => typeof entry === "string" && path.isAbsolute(entry),
  );
  return { version: 1, entries: [...new Set(entries)].toSorted() };
}

function writeWrapperState(statePath: string, state: WrapperState): void {
  const content = `${JSON.stringify(state, null, 2)}\n`;
  try {
    if (fs.readFileSync(statePath, "utf8") === content) {
      return;
    }
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw new Error(`read ${statePath} (${panicMessage(error)})`, { cause: error });
    }
  }
  const tempPath = `${statePath}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, content, "utf8");
  try {
    fs.renameSync(tempPath, statePath);
  } catch (error) {
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {
      // Best effort cleanup; preserve the original replacement error.
    }
    throw new Error(`replace ${statePath} (${panicMessage(error)})`, { cause: error });
  }
}

function writeManagedWrapper(targetPath: string, content: string): "owned" | "conflict" {
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
      throw new Error(`inspect wrapper ${targetPath} (${panicMessage(error)})`, { cause: error });
    }
  }

  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  const tempPath = `${targetPath}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, content, "utf8");
  fs.chmodSync(tempPath, 0o755);
  try {
    fs.renameSync(tempPath, targetPath);
  } catch (error) {
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {
      // Best effort cleanup; preserve the original replacement error.
    }
    throw new Error(`replace wrapper ${targetPath} (${panicMessage(error)})`, { cause: error });
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
      throw new Error(`remove wrapper ${targetPath} (${panicMessage(error)})`, { cause: error });
    }
  }
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
