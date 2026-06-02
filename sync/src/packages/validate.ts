import fs from "node:fs";
import { extname, join } from "node:path";

export const RESOURCE_KEYS = [
  "extensions",
  "skills",
  "prompts",
  "themes",
] as const;

const BUILTIN_PACKAGE_ROOTS = new Set([
  "assert",
  "buffer",
  "child_process",
  "cluster",
  "console",
  "constants",
  "crypto",
  "dgram",
  "diagnostics_channel",
  "dns",
  "domain",
  "events",
  "fs",
  "http",
  "http2",
  "https",
  "inspector",
  "module",
  "net",
  "os",
  "path",
  "perf_hooks",
  "process",
  "punycode",
  "querystring",
  "readline",
  "repl",
  "stream",
  "string_decoder",
  "timers",
  "tls",
  "tty",
  "url",
  "util",
  "v8",
  "vm",
  "worker_threads",
  "zlib",
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function packageIsHealthy(dir: string): boolean {
  if (!isDirectory(dir)) {
    return false;
  }
  if (missingPackageRoots(dir).length > 0) {
    return false;
  }

  const packageJsonPath = join(dir, "package.json");
  if (isFile(packageJsonPath)) {
    const packageJson = readJsonFile(packageJsonPath);
    if (isRecord(packageJson)) {
      const pi = packageJson.pi;
      if (isRecord(pi)) {
        const validated = validatePiManifest(dir, pi);
        if (validated !== null) {
          return validated;
        }
      }
    }
  }

  return RESOURCE_KEYS.some((key) => exists(join(dir, key)));
}

export function packageHasBuildScript(dir: string): boolean {
  const packageJsonPath = join(dir, "package.json");
  if (!isFile(packageJsonPath)) {
    return false;
  }

  const packageJson = readJsonFile(packageJsonPath);
  if (!isRecord(packageJson)) {
    return false;
  }

  const scripts = packageJson.scripts;
  return isRecord(scripts) && Object.hasOwn(scripts, "build");
}

export function missingPackageRoots(dir: string): string[] {
  const missing = new Set<string>();
  for (const file of packageSourceFiles(dir)) {
    const content = fs.readFileSync(file, "utf8");
    for (const specifier of extractImportSpecifiers(content)) {
      const packageRoot = packageRootFromSpecifier(specifier);
      if (!packageRoot || packageRootIsBuiltin(packageRoot)) {
        continue;
      }
      if (!exists(join(dir, "node_modules", packageRoot))) {
        missing.add(packageRoot);
      }
    }
  }
  return [...missing].sort();
}

export const validatePackageForTests = (dir: string): boolean =>
  packageIsHealthy(dir);

function validatePiManifest(
  dir: string,
  pi: Record<string, unknown>,
): boolean | null {
  let hasEntries = false;
  for (const key of RESOURCE_KEYS) {
    const entries = pi[key];
    if (!Array.isArray(entries)) {
      continue;
    }
    for (const entry of entries) {
      if (typeof entry !== "string") {
        continue;
      }
      if (isPatternEntry(entry)) {
        continue;
      }
      hasEntries = true;
      if (!exists(join(dir, entry))) {
        return false;
      }
    }
  }

  return hasEntries ? true : null;
}

const isPatternEntry = (value: string): boolean =>
  value.startsWith("!") ||
  value.startsWith("+") ||
  value.startsWith("-") ||
  value.includes("*") ||
  value.includes("?");

function readJsonFile(path: string): unknown | null {
  const content = readFile(path);
  try {
    return JSON.parse(content);
  } catch (error) {
    throw new Error(`parse ${path} (${String(error)})`);
  }
}

function readFile(path: string): string {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`read ${path} (${String(error)})`);
  }
}

function packageSourceFiles(root: string): string[] {
  if (!isDirectory(root)) {
    return [];
  }
  const files: string[] = [];
  walk(root, files);
  return files;
}

function walk(root: string, files: string[]): void {
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const entryPath = join(root, entry.name);

    if (entry.isDirectory()) {
      if (
        entry.name.startsWith(".") ||
        entry.name === "node_modules" ||
        entry.name === ".git"
      ) {
        continue;
      }
      walk(entryPath, files);
      continue;
    }

    if (entry.isSymbolicLink()) {
      try {
        const metadata = fs.statSync(entryPath);
        if (metadata.isDirectory()) {
          if (
            entry.name.startsWith(".") ||
            entry.name === "node_modules" ||
            entry.name === ".git"
          ) {
            continue;
          }
          walk(entryPath, files);
        } else if (metadata.isFile() && isSourceFile(entryPath)) {
          files.push(entryPath);
        }
      } catch {
        // ignore broken links
      }
      continue;
    }

    if (entry.isFile() && isSourceFile(entryPath)) {
      files.push(entryPath);
    }
  }
}

function isSourceFile(path: string): boolean {
  const extension = extname(path);
  return (
    extension === ".ts" ||
    extension === ".js" ||
    extension === ".mts" ||
    extension === ".cts" ||
    extension === ".mjs" ||
    extension === ".cjs"
  );
}

function extractImportSpecifiers(content: string): string[] {
  const prefixes = [
    'from "',
    "from '",
    'import "',
    "import '",
    'require("',
    "require('",
    'import("',
    "import('",
  ] as const;

  const specifiers: string[] = [];
  for (const prefix of prefixes) {
    const quote = prefix.at(-1) ?? '"';
    let remainder = content;
    while (true) {
      const index = remainder.indexOf(prefix);
      if (index < 0) {
        break;
      }
      const afterPrefix = remainder.slice(index + prefix.length);
      const end = afterPrefix.indexOf(quote);
      if (end < 0) {
        break;
      }
      specifiers.push(afterPrefix.slice(0, end));
      remainder = afterPrefix.slice(end + 1);
    }
  }
  return specifiers;
}

function packageRootFromSpecifier(specifier: string): string | null {
  const trimmed = specifier.trim();
  if (
    trimmed.length === 0 ||
    trimmed.startsWith(".") ||
    trimmed.startsWith("/") ||
    trimmed.startsWith("node:") ||
    trimmed.startsWith("bun:") ||
    trimmed.startsWith("data:") ||
    trimmed === "bun"
  ) {
    return null;
  }

  if (trimmed.startsWith("@")) {
    const parts = trimmed.slice(1).split("/");
    if (parts.length < 2 || !parts[0] || !parts[1]) {
      return null;
    }
    return `@${parts[0]}/${parts[1]}`;
  }

  return trimmed.split("/")[0] ?? null;
}

const packageRootIsBuiltin = (packageRoot: string): boolean =>
  BUILTIN_PACKAGE_ROOTS.has(packageRoot);

function isDirectory(path: string): boolean {
  try {
    return fs.statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function isFile(path: string): boolean {
  try {
    return fs.statSync(path).isFile();
  } catch {
    return false;
  }
}

function exists(path: string): boolean {
  try {
    fs.accessSync(path);
    return true;
  } catch {
    return false;
  }
}
