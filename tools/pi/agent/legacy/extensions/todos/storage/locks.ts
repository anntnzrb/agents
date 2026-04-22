/**
 * Locking helpers for todos.
 */

import fs from "node:fs/promises";
import path from "node:path";
import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import { LOCK_TTL_MS } from "../constants.ts";
import type { LockInfo } from "../types.ts";
import { displayTodoId } from "../utils.ts";

const getLockPath = (todosDir: string, id: string): string => {
  return path.join(todosDir, `${id}.lock`);
};

const readLockInfo = async (lockPath: string): Promise<LockInfo | null> => {
  try {
    const raw = await fs.readFile(lockPath, "utf8");
    return JSON.parse(raw) as LockInfo;
  } catch {
    return null;
  }
};

const acquireLock = async (
  todosDir: string,
  id: string,
  ctx: ExtensionContext
): Promise<(() => Promise<void>) | { error: string }> => {
  const lockPath = getLockPath(todosDir, id);
  const now = Date.now();
  const session = ctx.sessionManager.getSessionFile();

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const handle = await fs.open(lockPath, "wx");
      const info: LockInfo = {
        id,
        pid: process.pid,
        session,
        created_at: new Date(now).toISOString(),
      };
      await handle.writeFile(JSON.stringify(info, null, 2), "utf8");
      await handle.close();
      return async () => {
        try {
          await fs.unlink(lockPath);
        } catch {
          // ignore
        }
      };
    } catch (error: unknown) {
      const record = error as { code?: string; message?: string };
      if (record?.code !== "EEXIST") {
        return { error: `Failed to acquire lock: ${record?.message ?? "unknown error"}` };
      }
      const stats = await fs.stat(lockPath).catch(() => null);
      const lockAge = stats ? now - stats.mtimeMs : LOCK_TTL_MS + 1;
      if (lockAge <= LOCK_TTL_MS) {
        const info = await readLockInfo(lockPath);
        const owner = info?.session ? ` (session ${info.session})` : "";
        return { error: `Todo ${displayTodoId(id)} is locked${owner}. Try again later.` };
      }
      if (!ctx.hasUI) {
        return {
          error: `Todo ${displayTodoId(id)} lock is stale; rerun in interactive mode to steal it.`,
        };
      }
      const ok = await ctx.ui.confirm(
        "Todo locked",
        `Todo ${displayTodoId(id)} appears locked. Steal the lock?`
      );
      if (!ok) {
        return { error: `Todo ${displayTodoId(id)} remains locked.` };
      }
      await fs.unlink(lockPath).catch(() => undefined);
    }
  }

  return { error: `Failed to acquire lock for todo ${displayTodoId(id)}.` };
};

export const withTodoLock = async <T>(
  todosDir: string,
  id: string,
  ctx: ExtensionContext,
  fn: () => Promise<T>
): Promise<T | { error: string }> => {
  const lock = await acquireLock(todosDir, id, ctx);
  if (typeof lock === "object" && "error" in lock) return lock;
  try {
    return await fn();
  } finally {
    await lock();
  }
};
