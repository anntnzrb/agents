import { dlopen, FFIType, toBuffer } from "bun:ffi";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { Context, Effect, Layer } from "effect";

import { installExtensionDeps } from "./install.ts";
import { HarnessId, SyncEnv } from "./harness.ts";
import { iterJobs, runJobs } from "./jobs.ts";
import { cleanManagedEntries, planManagedEntries, recordManagedEntries } from "./managed.ts";
import * as packages from "./packages.ts";

const SYNC_TIMEOUT_ENV = "AGENTS_SYNC_TIMEOUT_SECONDS";
const DEFAULT_SYNC_TIMEOUT_SECONDS = 15 * 60;
const SYNC_LOCK_FILE = "sync.lock";
const LOCK_EX = 2;
const LOCK_NB = 4;
const WOULD_BLOCK_ERRNOS = new Set([os.constants.errno.EAGAIN, os.constants.errno.EWOULDBLOCK]);

const libcPath = process.platform === "darwin" ? "libSystem.B.dylib" : "libc.so.6";
const libc = dlopen(libcPath, {
  flock: {
    args: [FFIType.i32, FFIType.i32],
    returns: FFIType.i32,
  },
  strerror: {
    args: [FFIType.i32],
    returns: FFIType.cstring,
  },
  ...(process.platform === "darwin"
    ? {
        __error: {
          args: [],
          returns: FFIType.ptr,
        },
      }
    : {
        __errno_location: {
          args: [],
          returns: FFIType.ptr,
        },
      }),
});

const libcSymbols = libc.symbols as unknown as {
  readonly flock: (fd: number, operation: number) => number;
  readonly strerror: (errno: number) => unknown;
  readonly __error?: () => number;
  readonly __errno_location?: () => number;
};
const errnoAccessor = (process.platform === "darwin" ? "__error" : "__errno_location") as
  | "__error"
  | "__errno_location";

class Logger extends Context.Tag("Logger")<
  Logger,
  {
    readonly err: (message: string) => Effect.Effect<void>;
  }
>() {}

const LoggerLive = Layer.succeed(Logger, {
  err: (message: string) => Effect.sync(() => err(message)),
});

export interface SyncLock {
  readonly fd: number;
}

export function err(message: string): void {
  console.error(`sync: ${message}`);
}

export function warn(message: string): void {
  console.error(`sync: warning: ${message}`);
}

export function panicMessage(payload: unknown): string {
  if (typeof payload === "string") {
    return payload;
  }
  if (payload instanceof Error) {
    return payload.message;
  }
  return "panic";
}

export function isSymlink(targetPath: string): boolean {
  try {
    return fs.lstatSync(targetPath).isSymbolicLink();
  } catch {
    return false;
  }
}

export function rmEntry(targetPath: string): void {
  try {
    const metadata = fs.lstatSync(targetPath);
    if (metadata.isSymbolicLink() || metadata.isFile()) {
      fs.unlinkSync(targetPath);
      return;
    }
    if (metadata.isDirectory()) {
      fs.rmSync(targetPath, { recursive: true, force: false });
      return;
    }
    fs.unlinkSync(targetPath);
  } catch (error) {
    if (!isNotFound(error)) {
      throw error;
    }
  }
}

export function copyTree(src: string, dst: string): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    return;
  }
  copyTreeRecursive(src, dst);
}

function copyTreeRecursive(src: string, dst: string): void {
  const metadata = fs.statSync(src);
  if (!metadata.isDirectory()) {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    return;
  }

  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const childSrc = path.join(src, entry.name);
    const childDst = path.join(dst, entry.name);
    const childMetadata = fs.statSync(childSrc);
    if (childMetadata.isDirectory()) {
      copyTreeRecursive(childSrc, childDst);
    } else {
      fs.mkdirSync(path.dirname(childDst), { recursive: true });
      fs.copyFileSync(childSrc, childDst);
    }
  }
}

export function parseTimeoutSeconds(value: string | undefined, defaultSeconds: number): number {
  const parsed = value ? Number.parseInt(value, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultSeconds;
}

export function syncTimeout(): number {
  return parseTimeoutSeconds(process.env[SYNC_TIMEOUT_ENV], DEFAULT_SYNC_TIMEOUT_SECONDS);
}

export function syncLockPath(syncEnv: SyncEnv): string {
  return path.join(syncEnv.managedStateHome, SYNC_LOCK_FILE);
}

export function tryAcquireSyncLock(syncEnv: SyncEnv): SyncLock | undefined {
  const lockPath = syncLockPath(syncEnv);

  try {
    fs.mkdirSync(syncEnv.managedStateHome, { recursive: true });
  } catch (error) {
    throw new Error(`create sync state dir ${syncEnv.managedStateHome} (${panicMessage(error)})`);
  }

  let fd = -1;
  try {
    fd = fs.openSync(lockPath, "a+");
  } catch (error) {
    throw new Error(`open sync lock ${lockPath} (${panicMessage(error)})`);
  }

  const closeLock = (): void => {
    try {
      if (fd !== -1) {
        fs.closeSync(fd);
      }
    } catch {
      // best effort
    } finally {
      fd = -1;
    }
  };

  const flockResult = libc.symbols.flock(fd, LOCK_EX | LOCK_NB);
  if (flockResult !== 0) {
    const errno = currentErrno();
    closeLock();
    if (isWouldBlockErrno(errno)) {
      return undefined;
    }
    throw new Error(`lock sync ${lockPath} (${systemErrorMessage(errno)})`);
  }

  try {
    fs.ftruncateSync(fd, 0);
  } catch (error) {
    closeLock();
    throw new Error(`clear sync lock ${lockPath} (${panicMessage(error)})`);
  }

  try {
    fs.writeFileSync(fd, `pid=${process.pid}\n`, "utf8");
  } catch (error) {
    closeLock();
    throw new Error(`write sync lock ${lockPath} (${panicMessage(error)})`);
  }

  return { fd };
}

function releaseSyncLock(lock: SyncLock): void {
  try {
    fs.closeSync(lock.fd);
  } catch {
    // best effort
  }
}

export function startSyncWatchdog(timeoutSeconds: number): void {
  const timer = setTimeout(() => {
    err(`timed out after ${timeoutSeconds}s`);
    process.exit(124);
  }, timeoutSeconds * 1000);
  timer.unref();
}

export async function runSync(syncEnv: SyncEnv): Promise<boolean> {
  let managedPlan;
  try {
    managedPlan = planManagedEntries(syncEnv);
  } catch (error) {
    err(panicMessage(error));
    return false;
  }

  const cleanupSuccess = cleanManagedEntries(managedPlan);
  const baseSuccess = cleanupSuccess
    ? (() => {
        try {
          const jobs = iterJobs(syncEnv);
          return runJobs(jobs);
        } catch (error) {
          err(panicMessage(error));
          return false;
        }
      })()
    : false;

  const managedStateSuccess = baseSuccess ? recordManagedEntries(managedPlan) : true;
  const postSyncReady = baseSuccess && managedStateSuccess;
  const packageSuccess = postSyncReady ? await packages.bootstrapPackages(syncEnv) : true;
  const installSuccess = postSyncReady
    ? await (() => {
        const harness = syncEnv.harness(HarnessId.Pi);
        return harness
          ? Effect.runPromise(
              installExtensionDeps(
                path.join(harness.root(), "extensions"),
                syncEnv.installTimeoutMs,
              ) as Effect.Effect<boolean>
            )
          : Promise.resolve(true);
      })()
    : true;

  return baseSuccess && managedStateSuccess && packageSuccess && installSuccess;
}

export const main = (): Effect.Effect<number> =>
  Effect.gen(function* () {
    const logger = yield* Logger;
    const syncEnvResult = yield* Effect.either(
      Effect.try({
        try: () => SyncEnv.fromSystem(),
        catch: (error) => panicMessage(error),
      })
    );
    if (syncEnvResult._tag === "Left") {
      yield* logger.err(syncEnvResult.left);
      return 1;
    }
    const syncEnv = syncEnvResult.right;

    return yield* Effect.scoped(
      Effect.gen(function* () {
        const lockResult = yield* Effect.either(
          Effect.acquireRelease(
            Effect.try({
              try: () => tryAcquireSyncLock(syncEnv),
              catch: (error) => panicMessage(error),
            }),
            (lock) => Effect.sync(() => {
              if (lock) {
                releaseSyncLock(lock);
              }
            })
          )
        );

        if (lockResult._tag === "Left") {
          yield* logger.err(lockResult.left);
          return 1;
        }
        if (!lockResult.right) {
          yield* logger.err("another sync is already running; skipping");
          return 0;
        }

        startSyncWatchdog(syncTimeout());
        const success = yield* Effect.promise(() => runSync(syncEnv));
        return success ? 0 : 1;
      })
    );
  }).pipe(Effect.provide(LoggerLive));

function isNotFound(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "ENOENT"
  );
}

function currentErrno(): number {
  const errnoFn = libcSymbols[errnoAccessor];
  if (!errnoFn) {
    throw new Error("missing errno accessor");
  }
  const errnoPtr = errnoFn();
  return toBuffer(errnoPtr as never, 0, 4).readInt32LE(0);
}

function isWouldBlockErrno(errno: number): boolean {
  return WOULD_BLOCK_ERRNOS.has(errno);
}

function systemErrorMessage(errno: number): string {
  return `${String(libcSymbols.strerror(errno))} (os error ${errno})`;
}
