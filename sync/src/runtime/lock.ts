import { dlopen, FFIType, toBuffer } from "bun:ffi";
import fs from "node:fs";
import os from "node:os";

import { isErrno, panicMessage } from "./errors.ts";

const IS_WINDOWS = process.platform === "win32";
const LOCK_EX = 2;
const LOCK_NB = 4;
const WOULD_BLOCK_ERRNOS = new Set(
  [os.constants.errno.EAGAIN, os.constants.errno.EWOULDBLOCK].filter(
    (value): value is number => typeof value === "number",
  ),
);

const posixLibc = IS_WINDOWS ? undefined : createPosixLibc();
const errnoAccessor = (
  process.platform === "darwin" ? "__error" : "__errno_location"
) as "__error" | "__errno_location";

interface PosixLibcSymbols {
  readonly flock: (fd: number, operation: number) => number;
  readonly strerror: (errno: number) => unknown;
  readonly __error?: () => number;
  readonly __errno_location?: () => number;
}

export interface SyncLock {
  readonly fd: number;
  readonly lockPath?: string;
}

export function tryAcquireSyncLock(
  stateDir: string,
  lockPath: string,
): SyncLock | undefined {
  try {
    fs.mkdirSync(stateDir, { recursive: true });
  } catch (error) {
    throw new Error(
      `create sync state dir ${stateDir} (${panicMessage(error)})`,
    );
  }

  if (IS_WINDOWS) {
    return tryAcquireWindowsSyncLock(lockPath);
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

  const flockResult = requirePosixLibc().flock(fd, LOCK_EX | LOCK_NB);
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

  if (lock.lockPath) {
    try {
      fs.unlinkSync(lock.lockPath);
    } catch {
      // best effort
    }
  }
}

function createPosixLibc(): PosixLibcSymbols {
  const libcPath =
    process.platform === "darwin" ? "libSystem.B.dylib" : "libc.so.6";
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

  return libc.symbols as unknown as PosixLibcSymbols;
}

function requirePosixLibc(): PosixLibcSymbols {
  if (!posixLibc) {
    throw new Error("posix libc is not available on this platform");
  }
  return posixLibc;
}

function currentErrno(): number {
  const errnoFn = requirePosixLibc()[errnoAccessor];
  if (!errnoFn) {
    throw new Error("missing errno accessor");
  }
  const errnoPtr = errnoFn();
  return toBuffer(errnoPtr as never, 0, 4).readInt32LE(0);
}

const systemErrorMessage = (errno: number): string =>
  `${String(requirePosixLibc().strerror(errno))} (os error ${errno})`;

function tryAcquireWindowsSyncLock(lockPath: string): SyncLock | undefined {
  const openExclusive = (): number | undefined => {
    try {
      return fs.openSync(lockPath, "wx");
    } catch (error) {
      if (isErrno(error, "EEXIST")) {
        return undefined;
      }
      throw new Error(`open sync lock ${lockPath} (${panicMessage(error)})`);
    }
  };

  let fd = openExclusive();
  if (fd === undefined) {
    if (!clearStaleWindowsLock(lockPath)) {
      return undefined;
    }
    fd = openExclusive();
    if (fd === undefined) {
      return undefined;
    }
  }

  try {
    fs.writeFileSync(fd, `pid=${process.pid}\n`, "utf8");
  } catch (error) {
    try {
      fs.closeSync(fd);
    } catch {
      // best effort
    }
    try {
      fs.unlinkSync(lockPath);
    } catch {
      // best effort
    }
    throw new Error(`write sync lock ${lockPath} (${panicMessage(error)})`);
  }

  return { fd, lockPath };
}

function clearStaleWindowsLock(lockPath: string): boolean {
  let content: string;
  try {
    content = fs.readFileSync(lockPath, "utf8");
  } catch (error) {
    return isErrno(error, "ENOENT");
  }

  const pid = parseLockPid(content);
  if (!pid || pid === process.pid) {
    return false;
  }
  if (isProcessRunning(pid)) {
    return false;
  }

  try {
    fs.unlinkSync(lockPath);
    return true;
  } catch (error) {
    return isErrno(error, "ENOENT");
  }
}

function parseLockPid(content: string): number | undefined {
  const match = content.match(/pid=(\d+)/);
  if (!match?.[1]) {
    return undefined;
  }
  const pid = Number.parseInt(match[1], 10);
  return Number.isFinite(pid) && pid > 0 ? pid : undefined;
}

function isProcessRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (isErrno(error, "EPERM")) {
      return true;
    }
    return false;
  }
}
