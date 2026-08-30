import { dlopen, FFIType, toBuffer } from "bun:ffi";
import fs from "node:fs";
import os from "node:os";

import { panicMessage } from "./errors.ts";

const LOCK_EX = 2;
const LOCK_NB = 4;
const WOULD_BLOCK_ERRNOS = new Set(
  [os.constants.errno.EAGAIN, os.constants.errno.EWOULDBLOCK].filter(
    (value): value is number => typeof value === "number",
  ),
);

const posixLibc = createPosixLibc();
const errnoAccessor: "__error" | "__errno_location" =
  process.platform === "darwin" ? "__error" : "__errno_location";

interface PosixLibcSymbols {
  readonly flock: (fd: number, operation: number) => number;
  readonly strerror: (errno: number) => unknown;
  readonly __error?: () => number;
  readonly __errno_location?: () => number;
}

export interface SyncLock {
  readonly fd: number;
}

export function tryAcquireSyncLock(stateDir: string, lockPath: string): SyncLock | undefined {
  try {
    fs.mkdirSync(stateDir, { recursive: true });
  } catch (error) {
    throw new Error(`create sync state dir ${stateDir} (${panicMessage(error)})`, { cause: error });
  }

  let fd = -1;
  try {
    fd = fs.openSync(lockPath, "a+");
  } catch (error) {
    throw new Error(`open sync lock ${lockPath} (${panicMessage(error)})`, { cause: error });
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

  const flockResult = posixLibc.flock(fd, LOCK_EX | LOCK_NB);
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
    throw new Error(`clear sync lock ${lockPath} (${panicMessage(error)})`, { cause: error });
  }

  try {
    fs.writeFileSync(fd, `pid=${process.pid}\n`, "utf8");
  } catch (error) {
    closeLock();
    throw new Error(`write sync lock ${lockPath} (${panicMessage(error)})`, { cause: error });
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

function createPosixLibc(): PosixLibcSymbols {
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

  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Bun FFI exposes untyped symbols at this boundary.
  return libc.symbols as unknown as PosixLibcSymbols;
}

function currentErrno(): number {
  const errnoFn = posixLibc[errnoAccessor];
  if (!errnoFn) {
    throw new Error("missing errno accessor");
  }
  const errnoPtr = errnoFn();
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Bun's pointer overload is represented as never.
  return toBuffer(errnoPtr as never, 0, 4).readInt32LE(0);
}

const systemErrorMessage = (errno: number): string =>
  `${String(posixLibc.strerror(errno))} (os error ${errno})`;
