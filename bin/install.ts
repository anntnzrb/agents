import { constants as fsConstants } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

import { Effect } from "effect";

import * as packages from "./packages.ts";

const detailFromOutput = (stdout: string, stderr: string): string => {
  if (stderr.trim()) {
    return stderr.trim();
  }
  if (stdout.trim()) {
    return stdout.trim();
  }
  return "unknown error";
};

export const iterExtensionPackages = (root: string): Effect.Effect<string[]> =>
  Effect.promise(async () => {
    const stat = await fs.stat(root).catch(() => undefined);
    if (!stat?.isDirectory()) {
      return [];
    }
    return walkExtensionPackages(root);
  });

const walkExtensionPackages = async (root: string): Promise<string[]> => {
  const packagesFound: string[] = [];

  const visit = async (current: string): Promise<void> => {
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.join(current, entry.name);
      if (entry.isSymbolicLink()) {
        continue;
      }
      if (entry.isDirectory()) {
        if (entry.name === "node_modules") {
          continue;
        }
        await visit(entryPath);
        continue;
      }
      if (entry.isFile() && entry.name === "package.json") {
        packagesFound.push(current);
      }
    }
  };

  await visit(root);
  return packagesFound;
};

export const commandExists = async (command: string): Promise<boolean> => {
  const pathVar = process.env.PATH;
  if (!pathVar) {
    return false;
  }

  const candidates = command.includes(path.sep)
    ? [command]
    : pathVar.split(path.delimiter).map((dir) => path.join(dir, command));

  for (const candidate of candidates) {
    try {
      const metadata = await fs.stat(candidate);
      if (!metadata.isFile()) {
        continue;
      }
      await fs.access(candidate, fsConstants.X_OK);
      return true;
    } catch {
      continue;
    }
  }
  return false;
};

export const readPipe = async (stream: NodeJS.ReadableStream | null): Promise<Buffer> => {
  if (!stream) {
    return Buffer.alloc(0);
  }

  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
};

export const runInstall = (
  command: readonly string[],
  packageDir: string,
  timeoutMs: number
)=>
  Effect.promise(async () => {
    try {
      const child = spawn(command[0]!, command.slice(1), {
        cwd: packageDir,
        stdio: ["ignore", "pipe", "pipe"],
      });

      const stdoutPromise = readPipe(child.stdout);
      const stderrPromise = readPipe(child.stderr);

      return await new Promise<boolean>((resolve, reject) => {
        let timedOut = false;
        const timer = setTimeout(() => {
          timedOut = true;
          child.kill("SIGKILL");
        }, timeoutMs);

        child.once("error", (error) => {
          clearTimeout(timer);
          const io = error as NodeJS.ErrnoException;
          if (io.code === "ENOENT") {
            console.error(`sync: missing installer: ${command[0]}`);
            resolve(false);
            return;
          }
          reject(error);
        });

        child.once("close", async (code) => {
          clearTimeout(timer);
          const stdout = (await stdoutPromise).toString("utf8");
          const stderr = (await stderrPromise).toString("utf8");

          if (timedOut) {
            console.error(`sync: deps install timed out in ${packageDir}: ${command[0]}`);
            resolve(false);
            return;
          }

          if (code === 0) {
            resolve(true);
            return;
          }

          console.error(
            `sync: deps install failed in ${packageDir}: ${command[0]} (${detailFromOutput(
              stdout,
              stderr
            )})`
          );
          resolve(false);
        });
      });
    } catch (error) {
      throw error as Error;
    }
  }).pipe(
    Effect.catchAll((error) => {
      throw error as Error;
    })
  );

const needsNodeInstall = async (packageDir: string): Promise<boolean> => {
  const packageJson = await fs
    .stat(path.join(packageDir, "package.json"))
    .then((metadata) => metadata.isFile())
    .catch(() => false);
  const nodeModules = await fs.stat(path.join(packageDir, "node_modules")).catch(() => undefined);
  return packageJson && !nodeModules;
};

const chooseInstaller = async (packageDir: string): Promise<string[] | undefined> => {
  if (
    (await fs.stat(path.join(packageDir, "bun.lockb")).catch(() => undefined)) &&
    (await commandExists("bun"))
  ) {
    return ["bun", "install"];
  }
  if (await commandExists("npm")) {
    return ["npm", "install"];
  }
  if (await commandExists("bun")) {
    return ["bun", "install"];
  }
  return undefined;
};

export const installExtensionDeps = (root: string, timeoutMs: number) =>
  Effect.gen(function* () {
    const results: boolean[] = [];
    for (const packageDir of yield* iterExtensionPackages(root)) {
      if (!(yield* Effect.promise(() => needsNodeInstall(packageDir)))) {
        results.push(true);
        continue;
      }

      const command = yield* Effect.promise(() => chooseInstaller(packageDir));
      if (!command) {
        console.error(`sync: no package manager available for ${packageDir}`);
        results.push(false);
        continue;
      }

      results.push((yield* runInstall(command, packageDir, timeoutMs)) as boolean);
    }
    results.push(yield* Effect.promise(() => packages.installInferredImportPackages(root, timeoutMs)));
    return results.every(Boolean);
  });
