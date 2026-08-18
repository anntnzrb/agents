/**
 * Locking helpers for todos.
 */

import { Effect, Schema } from "effect";
import fs from "node:fs/promises";
import path from "node:path";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { LOCK_TTL_MS } from "../constants.ts";
import type { LockInfo } from "../types.ts";
import { displayTodoId } from "../utils.ts";

export class TodoLockError extends Schema.TaggedError<TodoLockError>()("TodoLockError", {
  id: Schema.String,
  message: Schema.String,
}) {}

export class TodoLockIoError extends Schema.TaggedError<TodoLockIoError>()("TodoLockIoError", {
  path: Schema.String,
  message: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {}

export class TodoOperationError extends Schema.TaggedError<TodoOperationError>()("TodoOperationError", {
  message: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {}

const lockIoError = (
  lockPath: string,
  operation: string,
  cause: unknown,
): TodoLockIoError =>
  new TodoLockIoError({
    path: lockPath,
    message: `${operation} ${lockPath}: ${cause instanceof Error ? cause.message : String(cause)}`,
    cause,
  });

const getLockPath = (todosDir: string, id: string): string =>
  path.join(todosDir, `${id}.lock`);

const bestEffort = <A>(operation: () => Promise<A>): Effect.Effect<A | undefined> =>
  Effect.promise(async () => {
    try {
      return await operation();
    } catch {
      return undefined;
    }
  });

const readLockInfoEffect = Effect.fn("readTodoLockInfo")((lockPath: string) =>
  Effect.promise(async () => {
    try {
      return JSON.parse(await fs.readFile(lockPath, "utf8")) as LockInfo;
    } catch {
      return null;
    }
  }),
);

const removeLockEffect = (lockPath: string): Effect.Effect<void> =>
  bestEffort(() => fs.unlink(lockPath)).pipe(Effect.asVoid);

const createLockFileEffect = (
  lockPath: string,
  info: LockInfo,
): Effect.Effect<void, TodoLockIoError> =>
  Effect.acquireUseRelease(
    Effect.tryPromise({
      try: () => fs.open(lockPath, "wx"),
      catch: (cause) => lockIoError(lockPath, "Unable to open todo lock", cause),
    }),
    (handle) =>
      Effect.tryPromise({
        try: () => handle.writeFile(JSON.stringify(info, null, 2), "utf8"),
        catch: (cause) => lockIoError(lockPath, "Unable to write todo lock", cause),
      }),
    (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
  );

export const acquireLockEffect = Effect.fn("acquireTodoLock")(function*(
  todosDir: string,
  id: string,
  ctx: ExtensionContext,
): Effect.fn.Return<string, TodoLockError | TodoLockIoError> {
  const lockPath = getLockPath(todosDir, id);
  const now = Date.now();
  const info: LockInfo = {
    id,
    pid: process.pid,
    session: ctx.sessionManager.getSessionFile(),
    created_at: new Date(now).toISOString(),
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const created = yield* createLockFileEffect(lockPath, info).pipe(
      Effect.as({ ok: true as const }),
      Effect.catch((error) => Effect.succeed({ ok: false as const, error })),
    );
    if (created.ok) return lockPath;

    const error = created.error;
    if (!(
      typeof error.cause === "object" &&
      error.cause !== null &&
      "code" in error.cause &&
      error.cause.code === "EEXIST"
    )) {
      yield* removeLockEffect(lockPath);
      return yield* new TodoLockError({
        id,
        message: `Failed to acquire lock: ${error.message}`,
      });
    }

    const stats = yield* bestEffort(() => fs.stat(lockPath));
    const lockAge = stats ? now - stats.mtimeMs : LOCK_TTL_MS + 1;
    if (lockAge <= LOCK_TTL_MS) {
      const owner = yield* readLockInfoEffect(lockPath);
      const session = owner?.session ? ` (session ${owner.session})` : "";
      return yield* new TodoLockError({
        id,
        message: `Todo ${displayTodoId(id)} is locked${session}. Try again later.`,
      });
    }

    if (!ctx.hasUI) {
      return yield* new TodoLockError({
        id,
        message: `Todo ${displayTodoId(id)} lock is stale; rerun in interactive mode to steal it.`,
      });
    }

    const steal = yield* Effect.tryPromise({
      try: () =>
        ctx.ui.confirm(
          "Todo locked",
          `Todo ${displayTodoId(id)} appears locked. Steal the lock?`,
        ),
      catch: (cause) => lockIoError(lockPath, "Unable to confirm stale todo lock", cause),
    });
    if (!steal) {
      return yield* new TodoLockError({
        id,
        message: `Todo ${displayTodoId(id)} remains locked.`,
      });
    }

    yield* removeLockEffect(lockPath);
  }

  return yield* new TodoLockError({
    id,
    message: `Failed to acquire lock for todo ${displayTodoId(id)}.`,
  });
});

export const withTodoLock = async <T>(
  todosDir: string,
  id: string,
  ctx: ExtensionContext,
  fn: () => Promise<T>,
): Promise<T | { error: string }> =>
  Effect.runPromise(
    acquireLockEffect(todosDir, id, ctx).pipe(
      Effect.flatMap((lockPath) =>
        Effect.acquireUseRelease(
          Effect.succeed(lockPath),
          () =>
            Effect.tryPromise({
              try: fn,
              catch: (cause) => new TodoOperationError({
                message: cause instanceof Error ? cause.message : String(cause),
                cause,
              }),
            }),
          removeLockEffect,
        ),
      ),
      Effect.catchTag("TodoLockError", (error) =>
        Effect.succeed({ error: error.message }),
      ),
    ),
  );
