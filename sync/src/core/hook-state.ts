import { createHash } from "node:crypto";
import fs from "node:fs";
import { dirname, join, relative, sep } from "node:path";

import { isErrno } from "@runtime/errors.ts";
import type { ExtensionDepsHookPlan } from "./plan.ts";

const GENERATED_EXTENSION_ENTRY_NAMES = [
  "package.json",
  "node_modules",
  "bun.lock",
  "bun.lockb",
] as const;

interface ExtensionHookStateFile {
  readonly fingerprint: string;
  readonly generatedEntries: readonly string[];
}

export interface PreparedExtensionHookState {
  readonly fingerprint: string;
  readonly generatedEntries: readonly string[];
  readonly preservePaths: readonly string[];
  readonly shouldSkip: boolean;
}

export function prepareExtensionHookState(hook: ExtensionDepsHookPlan): PreparedExtensionHookState {
  const fingerprint = fingerprintTree(hook.sourceRoot);
  const previousState = loadExtensionHookState(hook.statePath);
  if (!previousState || previousState.fingerprint !== fingerprint) {
    return {
      fingerprint,
      generatedEntries: [],
      preservePaths: [],
      shouldSkip: false,
    };
  }

  const generatedEntries = previousState.generatedEntries.filter((entryName) =>
    exists(join(hook.root, entryName)),
  );
  const shouldSkip = generatedEntries.length === previousState.generatedEntries.length;
  return {
    fingerprint,
    generatedEntries,
    preservePaths: shouldSkip
      ? generatedEntries.map((entryName) => joinRelative(hook.relativeRoot, entryName))
      : [],
    shouldSkip,
  };
}

export function recordExtensionHookState(
  hook: ExtensionDepsHookPlan,
  preparedState: PreparedExtensionHookState,
): void {
  const state: ExtensionHookStateFile = {
    fingerprint: preparedState.fingerprint,
    generatedEntries: GENERATED_EXTENSION_ENTRY_NAMES.filter((entryName) =>
      exists(join(hook.root, entryName)),
    ),
  };
  writeHookStateFile(hook.statePath, state);
}

export function clearExtensionHookState(statePath: string): void {
  try {
    fs.rmSync(statePath, { force: true });
  } catch {
    // best effort
  }
}

export function fingerprintTree(root: string): string {
  const hash = createHash("sha256");
  if (!exists(root)) {
    hash.update("missing");
    return hash.digest("hex");
  }
  walkTree(root, root, hash);
  return hash.digest("hex");
}

function walkTree(root: string, current: string, hash: ReturnType<typeof createHash>): void {
  const entries = fs.readdirSync(current, { withFileTypes: true }).sort((left, right) =>
    left.name.localeCompare(right.name),
  );

  for (const entry of entries) {
    if (shouldSkipEntry(entry.name)) {
      continue;
    }

    const absolute = join(current, entry.name);
    const relativePath = normalizeRelativePath(relative(root, absolute));
    if (entry.isDirectory()) {
      hash.update(`dir:${relativePath}\n`);
      walkTree(root, absolute, hash);
      continue;
    }
    if (entry.isSymbolicLink()) {
      try {
        const metadata = fs.statSync(absolute);
        if (metadata.isDirectory()) {
          hash.update(`dir:${relativePath}\n`);
          walkTree(root, absolute, hash);
          continue;
        }
      } catch {
        hash.update(`broken:${relativePath}\n`);
        continue;
      }
    }
    if (!entry.isFile() && !entry.isSymbolicLink()) {
      continue;
    }
    hash.update(`file:${relativePath}\n`);
    hash.update(fs.readFileSync(absolute));
    hash.update("\n");
  }
}

function loadExtensionHookState(path: string): ExtensionHookStateFile | undefined {
  let content: string;
  try {
    content = fs.readFileSync(path, "utf8");
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return undefined;
    }
    warn(`hook state read failed, ignoring ${path} (${String(error)})`);
    return undefined;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch (error) {
    warn(`hook state parse failed, ignoring ${path} (${String(error)})`);
    return undefined;
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    warn(`hook state parse failed, ignoring ${path} (not an object)`);
    return undefined;
  }

  const fingerprint = (parsed as { fingerprint?: unknown }).fingerprint;
  const generatedEntries = (parsed as { generatedEntries?: unknown }).generatedEntries;
  if (typeof fingerprint !== "string" || !Array.isArray(generatedEntries)) {
    warn(`hook state parse failed, ignoring ${path} (invalid shape)`);
    return undefined;
  }
  if (!generatedEntries.every((entry) => typeof entry === "string")) {
    warn(`hook state parse failed, ignoring ${path} (generated entries must be strings)`);
    return undefined;
  }

  return {
    fingerprint,
    generatedEntries: [...new Set(generatedEntries)].sort(),
  };
}

function writeHookStateFile(path: string, state: ExtensionHookStateFile): void {
  fs.mkdirSync(dirname(path), { recursive: true });
  const tempPath = `${path}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  fs.renameSync(tempPath, path);
}

function exists(targetPath: string): boolean {
  try {
    fs.accessSync(targetPath);
    return true;
  } catch {
    return false;
  }
}

const shouldSkipEntry = (entryName: string): boolean => entryName === "node_modules" || entryName === ".git" || entryName.startsWith(".");

const normalizeRelativePath = (pathValue: string): string => pathValue.split(sep).join("/");

const joinRelative = (left: string, right: string): string => left.length === 0 ? right : `${left}/${right}`;


function warn(message: string): void {
  console.error(`sync: warning: ${message}`);
}
