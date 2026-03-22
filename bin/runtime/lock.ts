import { dlopen, FFIType, toBuffer } from "bun:ffi";
import fs from "node:fs";
import os from "node:os";

import { panicMessage } from "./errors.ts";

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

export interface SyncLock {
  readonly fd: number;
}

export function tryAcquireSyncLock(stateDir: string, lockPath: string): SyncLock | undefined {
  try {
    fs.mkdirSync(stateDir, { recursive: true });
  } catch (error) {
    throw new Error(`create sync state dir ${stateDir} (${panicMessage(error)})`);
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

  const flockResult = libcSymbols.flock(fd, LOCK_EX | LOCK_NB);
  if (flockResult !== 0) {
    const errno = currentErrno();
    closeLock();
    if (WOULD_BLOCK_ERRNOS.has(errno)) {
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

export function releaseSyncLock(lock: SyncLock): void {
  try {
    fs.closeSync(lock.fd);
  } catch {
    // best effort
  }
}

function currentErrno(): number {
  const errnoFn = libcSymbols[errnoAccessor];
  if (!errnoFn) {
    throw new Error("missing errno accessor");
  }
  const errnoPtr = errnoFn();
  return toBuffer(errnoPtr as never, 0, 4).readInt32LE(0);
}

function systemErrorMessage(errno: number): string {
  return `${String(libcSymbols.strerror(errno))} (os error ${errno})`;
}
