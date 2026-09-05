import fs from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { isErrno } from "@runtime/errors.ts";
import { isIgnoredSyncEntry } from "@runtime/fs.ts";
import { Schema } from "effect";
import type { ExtensionDepsHookPlan } from "./plan.ts";

const ExtensionHookStateSchema = Schema.Struct({
  fingerprint: Schema.String,
  generatedEntries: Schema.Array(Schema.String),
});

const GENERATED_EXTENSION_ENTRY_NAMES = [
  "package.json",
  "node_modules",
  "bun.lock",
  "bun.lockb",
] as const;
const GENERATED_EXTENSION_ENTRY_NAME_RECORD: Record<string, true> = {
  "package.json": true,
  node_modules: true,
  "bun.lock": true,
  "bun.lockb": true,
};
interface ExtensionHookStateFile {
  readonly fingerprint: string;
  readonly generatedEntries: readonly string[];
}

interface LoadedExtensionHookState extends ExtensionHookStateFile {
  readonly shouldRefreshState: boolean;
}

export interface PreparedExtensionHookState {
  readonly fingerprint: string;
  readonly generatedEntries: readonly string[];
  readonly preservePaths: readonly string[];
  readonly shouldSkip: boolean;
  readonly shouldRefreshState: boolean;
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
      shouldRefreshState: false,
    };
  }

  const generatedEntries = previousState.generatedEntries.filter((entryName) =>
    exists(join(hook.root, entryName)),
  );
  const shouldSkip = generatedEntries.length === previousState.generatedEntries.length;
  const shouldRefreshState = previousState.shouldRefreshState;
  return {
    fingerprint,
    generatedEntries,
    preservePaths: shouldSkip
      ? generatedEntries.map((entryName) => joinRelative(hook.relativeRoot, entryName))
      : [],
    shouldSkip,
    shouldRefreshState,
  };
}

export function recordExtensionHookState(
  hook: ExtensionDepsHookPlan,
  preparedState: PreparedExtensionHookState,
): void {
  const state: ExtensionHookStateFile = {
    fingerprint: preparedState.fingerprint,
    generatedEntries: findGeneratedExtensionEntries(hook.root),
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
  const hash = new Bun.CryptoHasher("sha256");
  if (!exists(root)) {
    hash.update("missing");
    return hash.digest("hex");
  }
  walkTree(root, root, hash);
  return hash.digest("hex");
}

function walkTree(
  root: string,
  current: string,
  hash: InstanceType<typeof Bun.CryptoHasher>,
): void {
  const entries = fs
    .readdirSync(current, { withFileTypes: true })
    .toSorted((left, right) => (left.name < right.name ? -1 : left.name > right.name ? 1 : 0));

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
          throw new Error(`refusing source directory symlink: ${absolute}`);
        }
      } catch (error) {
        if (isErrno(error, "ENOENT")) {
          hash.update(`broken:${relativePath}\n`);
          continue;
        }
        throw error;
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

function loadExtensionHookState(path: string): LoadedExtensionHookState | undefined {
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
    parsed = Bun.JSONC.parse(content);
  } catch (error) {
    warn(`hook state parse failed, ignoring ${path} (${String(error)})`);
    return undefined;
  }

  let decoded: { readonly fingerprint: string; readonly generatedEntries: readonly string[] };
  try {
    decoded = Schema.decodeUnknownSync(ExtensionHookStateSchema)(parsed);
  } catch {
    warn(
      `hook state parse failed, ignoring ${path} (${typeof parsed !== "object" || parsed === null || Array.isArray(parsed) ? "not an object" : "invalid shape"})`,
    );
    return undefined;
  }

  const normalizedGeneratedEntries = [...new Set(decoded.generatedEntries)].toSorted();
  const filteredGeneratedEntries = normalizedGeneratedEntries.filter(isGeneratedExtensionEntryName);

  return {
    fingerprint: decoded.fingerprint,
    generatedEntries: filteredGeneratedEntries,
    shouldRefreshState: filteredGeneratedEntries.length !== normalizedGeneratedEntries.length,
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

const shouldSkipEntry = (entryName: string): boolean =>
  entryName === "node_modules" ||
  entryName === ".git" ||
  entryName.startsWith(".") ||
  isIgnoredSyncEntry(entryName);

const normalizeRelativePath = (pathValue: string): string => pathValue.split(sep).join("/");

const joinRelative = (left: string, right: string): string =>
  left.length === 0 ? right : `${left}/${right}`;

function findGeneratedExtensionEntries(root: string): string[] {
  const results: string[] = [];
  for (const entryName of GENERATED_EXTENSION_ENTRY_NAMES) {
    if (exists(join(root, entryName))) {
      results.push(entryName);
    }
  }

  try {
    for (const child of fs.readdirSync(root, { withFileTypes: true })) {
      if (child.isDirectory() && !shouldSkipEntry(child.name)) {
        for (const entryName of GENERATED_EXTENSION_ENTRY_NAMES) {
          const relativePath = `${child.name}/${entryName}`;
          if (exists(join(root, relativePath))) {
            results.push(relativePath);
          }
        }
      }
    }
  } catch {
    // best effort
  }

  return [...new Set(results)];
}

const isGeneratedExtensionEntryName = (entryName: string): boolean => {
  const baseName = entryName.includes("/")
    ? entryName.slice(entryName.lastIndexOf("/") + 1)
    : entryName;
  return GENERATED_EXTENSION_ENTRY_NAME_RECORD[baseName] === true;
};

function warn(message: string): void {
  console.error(`sync: warning: ${message}`);
}
