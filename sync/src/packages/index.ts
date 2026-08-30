import fs from "node:fs";
import path from "node:path";
import { isErrno, panicMessage } from "@runtime/errors.ts";
import { Schema, SchemaGetter } from "effect";

import {
  installInferredImportPackages as installInferredImportPackagesImpl,
  installPackageDeps,
  runPackageBuild,
} from "./process.ts";
import {
  clonePackage,
  packageCacheDir,
  replaceDirAtomically,
  rmEntry,
  stagingDirFor,
} from "./source.ts";
import { packageHasBuildScript, packageIsHealthy } from "./validate.ts";

export { clonePackage, packageCacheDir } from "./source.ts";
export {
  extractImportSpecifiers,
  missingPackageRoots,
  packageHasBuildScript,
  packageIsHealthy,
  validatePackageForTests,
} from "./validate.ts";

export const PackageManifestSchema = Schema.Struct({
  packages: Schema.Array(Schema.NonEmptyString).pipe(
    Schema.decodeTo(Schema.Array(Schema.String), {
      decode: SchemaGetter.transform((pkgs) => [
        ...new Set(pkgs.map((p) => p.trim()).filter((p) => p.length > 0)),
      ]),
      encode: SchemaGetter.passthrough(),
    }),
  ),
});

export type PackageManifest = typeof PackageManifestSchema.Type;

export interface PackageBootstrapTarget {
  readonly manifestPath: string;
  readonly runtimeSettingsPath: string;
  readonly cacheRoot: string;
  readonly timeoutMs: number;
}

function err(message: string): void {
  console.error(`sync: ${message}`);
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function readPackageManifest(filePath: string): PackageManifest {
  let content: string;
  try {
    content = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    if (isErrno(error, "ENOENT")) {
      return { packages: [] };
    }
    throw new Error(`${filePath} (${String(error)})`, { cause: error });
  }

  let value: unknown;
  try {
    value = Bun.JSONC.parse(content);
  } catch (error) {
    throw new Error(`invalid JSON in ${filePath}: ${String(error)}`, { cause: error });
  }

  try {
    return Schema.decodeUnknownSync(PackageManifestSchema)(value);
  } catch (error) {
    throw new Error(`${filePath} (${panicMessage(error)})`, { cause: error });
  }
}

export function patchRuntimeSettings(filePath: string, packagePaths: readonly string[]): void {
  let current = "{}";
  try {
    current = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    if (!isErrno(error, "ENOENT")) {
      throw new Error(`read ${filePath} (${String(error)})`, { cause: error });
    }
  }

  let value: unknown;
  try {
    value = Bun.JSONC.parse(current);
  } catch (error) {
    throw new Error(`parse ${filePath} (${String(error)})`, { cause: error });
  }

  const settings = isRecord(value) ? value : {};
  settings["packages"] = [...packagePaths];

  const parent = path.dirname(filePath);
  if (parent && parent !== ".") {
    fs.mkdirSync(parent, { recursive: true });
  }

  try {
    fs.writeFileSync(filePath, `${JSON.stringify(settings, null, 2)}\n`);
  } catch (error) {
    throw new Error(`write ${filePath} (${String(error)})`, { cause: error });
  }
}

async function ensurePackage(
  source: string,
  cacheRoot: string,
  timeoutMs: number,
): Promise<string> {
  const finalDir = packageCacheDir(cacheRoot, source);
  if (packageIsHealthy(finalDir)) {
    return finalDir;
  }

  fs.mkdirSync(cacheRoot, { recursive: true });

  const stagingDir = stagingDirFor(finalDir);
  rmEntry(stagingDir);
  fs.mkdirSync(path.dirname(stagingDir), { recursive: true });

  try {
    if (!(await clonePackage(source, stagingDir, timeoutMs))) {
      throw new Error("clone failed");
    }
    if (!(await installPackageDeps(stagingDir, timeoutMs))) {
      throw new Error("dependency install failed");
    }

    let healthy = packageIsHealthy(stagingDir);
    if (!healthy && packageHasBuildScript(stagingDir)) {
      if (!(await runPackageBuild(stagingDir, timeoutMs))) {
        throw new Error("build failed");
      }
      if (!(await installInferredImportPackagesImpl(stagingDir, timeoutMs))) {
        throw new Error("install inferred packages after build failed");
      }
      healthy = packageIsHealthy(stagingDir);
    }

    if (!healthy) {
      throw new Error("package resources failed validation");
    }

    await replaceDirAtomically(stagingDir, finalDir);
    return finalDir;
  } catch (error) {
    rmEntry(stagingDir);
    throw error;
  }
}

export async function bootstrapPackageTarget(target: PackageBootstrapTarget): Promise<boolean> {
  let manifest: PackageManifest;
  try {
    manifest = readPackageManifest(target.manifestPath);
  } catch (error) {
    err(`package bootstrap failed: ${String(error instanceof Error ? error.message : error)}`);
    return false;
  }

  const installedPaths: string[] = [];
  let success = true;
  for (const source of manifest.packages) {
    try {
      installedPaths.push(await ensurePackage(source, target.cacheRoot, target.timeoutMs));
    } catch (error) {
      err(
        `package bootstrap failed for ${source}: ${String(error instanceof Error ? error.message : error)}`,
      );
      success = false;
    }
  }

  try {
    patchRuntimeSettings(target.runtimeSettingsPath, installedPaths);
  } catch (error) {
    err(`package settings patch failed: ${String(error instanceof Error ? error.message : error)}`);
    success = false;
  }

  return success;
}
