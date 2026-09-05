import fs from "node:fs";
import { join } from "node:path";

export const RESOURCE_KEYS = ["extensions", "skills", "prompts", "themes"] as const;

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
      const pi = packageJson["pi"];
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

  const scripts = packageJson["scripts"];
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
  return [...missing].toSorted();
}
function validatePiManifest(dir: string, pi: Record<string, unknown>): boolean | null {
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

function readJsonFile(path: string): unknown {
  const content = readFile(path);
  try {
    return Bun.JSONC.parse(content);
  } catch (error) {
    throw new Error(`parse ${path} (${String(error)})`, { cause: error });
  }
}

function readFile(path: string): string {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`read ${path} (${String(error)})`, { cause: error });
  }
}

function packageSourceFiles(root: string): string[] {
  if (!isDirectory(root)) {
    return [];
  }
  const glob = new Bun.Glob("**/*.{ts,js,mts,cts,mjs,cjs}");
  const files: string[] = [];
  try {
    for (const rel of glob.scanSync({ cwd: root, dot: false, followSymlinks: true })) {
      if (
        rel.startsWith("node_modules/") ||
        rel.includes("/node_modules/") ||
        rel.startsWith(".git/") ||
        rel.includes("/.git/")
      ) {
        continue;
      }
      files.push(join(root, rel));
    }
  } catch {
    return [];
  }
  return files;
}

const importScanner = new Bun.Transpiler({ loader: "ts" });

/**
 * Extracts runtime import specifiers from JavaScript or TypeScript source code.
 *
 * Uses `Bun.Transpiler` to scan the AST for ESM `import` statements, `export ... from`
 * statements, and dynamic `import()` calls. CommonJS `require("...")` calls are
 * pre-normalized to `import("...")` so the scanner treats them as dynamic imports.
 *
 * Parsing behavior and guarantees:
 * - Comment immunity: Single-line (`//`) and multiline block (`/* ... *\/`) comments are ignored.
 * - String/template immunity: Specifiers inside string literals or template literals are ignored.
 * - Type-only imports: Type-only imports (`import type { ... }`) are erased during transpilation.
 * - Specifier extraction: All runtime specifiers are returned as-is (package names, scoped packages,
 *   local relative paths, built-in schemes like `node:`/`bun:`, and `data:` URIs).
 */
export function extractImportSpecifiers(content: string): string[] {
  // Bun.Transpiler.scan tracks ESM imports and dynamic `import()` calls, but not
  // CommonJS `require()` calls. Normalize top-level/standalone `require("...")` calls
  // (excluding property access like `obj.require(...)`) so the scanner treats them
  // as dynamic imports while ignoring comments and strings.
  const normalized = content.replace(/(?<![.\w$])require\s*\(/g, "import(");
  try {
    return importScanner.scan(normalized).imports.map(({ path }) => path);
  } catch {
    return [];
  }
}
const VALID_PACKAGE_ROOT_PATTERN = /^(@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/i;

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
  let root: string;
  if (trimmed.startsWith("@")) {
    const parts = trimmed.slice(1).split("/");
    if (parts.length < 2 || !parts[0] || !parts[1]) {
      return null;
    }
    root = `@${parts[0]}/${parts[1]}`;
  } else {
    root = trimmed.split("/")[0] ?? "";
  }

  if (!VALID_PACKAGE_ROOT_PATTERN.test(root)) {
    return null;
  }
  return root;
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
