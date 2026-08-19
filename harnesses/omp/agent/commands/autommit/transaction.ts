import { Effect, Schema } from "effect";
import { lstat, mkdir, open, rename, unlink } from "node:fs/promises";
import { join, parse, resolve, sep } from "node:path";

const AUTOMMIT_DIRECTORY = "autommit";
const RECEIPT_FILENAME = "receipt.json";
const LOCK_FILENAME = "operation.lock";
const MAX_JSON_BYTES = 16 * 1024;
const MAX_STRING_LENGTH = 4 * 1024;
const MAX_LOCK_BYTES = 4 * 1024;

const RECEIPT_KEYS = ["version", "state", "ref", "before", "after", "indexTree"] as const;
const LOCK_KEYS = ["pid", "token"] as const;
const RECEIPT_STATES = ["prepared", "committed"] as const;

type ReceiptState = (typeof RECEIPT_STATES)[number];

type JsonRecord = Record<string, unknown>;

export interface Receipt {
    readonly version: 1;
    readonly state: ReceiptState;
    readonly ref: string;
    readonly before: string;
    readonly after: string;
    readonly indexTree: string;
}

interface LockOwner {
    readonly pid: number;
    readonly token: string;
}

interface Paths {
    readonly commonDir: string;
    readonly directory: string;
    readonly receipt: string;
    readonly lock: string;
}

export class AutommitPathError extends Schema.TaggedError<AutommitPathError>()("AutommitPathError", {
    message: Schema.String,
    target: Schema.String,
    cause: Schema.optional(Schema.Unknown),
}) {}

export class AutommitReceiptError extends Schema.TaggedError<AutommitReceiptError>()("AutommitReceiptError", {
    message: Schema.String,
    cause: Schema.optional(Schema.Unknown),
}) {}

export class AutommitLockError extends Schema.TaggedError<AutommitLockError>()("AutommitLockError", {
    message: Schema.String,
    cause: Schema.optional(Schema.Unknown),
}) {}

export class AutommitOperationError extends Schema.TaggedError<AutommitOperationError>()("AutommitOperationError", {
    message: Schema.String,
    cause: Schema.optional(Schema.Unknown),
}) {}

type AutommitTransactionError =
    | AutommitPathError
    | AutommitReceiptError
    | AutommitLockError
    | AutommitOperationError;

const isErrorCode = (error: unknown, code: string): boolean => {
    if (typeof error !== "object" || error === null || !("code" in error)) return false;
    return (error as { code?: unknown }).code === code;
};

const pathError = (operation: string, target: string, cause: unknown): AutommitPathError =>
    new AutommitPathError({
        message: `${operation} ${target}: ${cause instanceof Error ? cause.message : String(cause)}`,
        target,
        cause,
    });

const pathFailure = (message: string, target: string): AutommitPathError =>
    new AutommitPathError({ message, target });

const validateCommonDir = (commonDir: string): string => {
    if (typeof commonDir !== "string" || commonDir.length === 0 || commonDir.includes("\0")) {
        throw new TypeError("Git commonDir must be a non-empty path.");
    }
    return resolve(commonDir);
};

const ensureNoSymlinkPathEffect = Effect.fn("ensureNoSymlinkPath")(function*(
    target: string,
    allowMissingFinal: boolean,
    commonDir: string,
): Effect.fn.Return<boolean, AutommitPathError> {
    const absolute = resolve(target);
    const base = resolve(commonDir);
    const root = parse(absolute).root;
    const baseRoot = parse(base).root;
    const basePrefix = base.endsWith(sep) ? base : `${base}${sep}`;
    if (root !== baseRoot || (absolute !== base && !absolute.startsWith(basePrefix))) {
        return yield* pathFailure(`Autommit path is outside Git commonDir: ${absolute}`, absolute);
    }

    const relative = absolute === base ? "" : absolute.slice(base === baseRoot ? base.length : base.length + 1);
    const components = relative.split(sep).filter(Boolean);
    let current = base;

    for (const component of components.length === 0 ? [""] : components) {
        if (component) current = join(current, component);
        const result = yield* Effect.tryPromise({
            try: () => lstat(current),
            catch: (error) => error,
        }).pipe(
            Effect.map((stats) => ({ ok: true as const, stats })),
            Effect.catchAll((error) => Effect.succeed({ ok: false as const, error })),
        );

        if (result.ok) {
            if (result.stats.isSymbolicLink()) {
                return yield* pathFailure(`Refusing symlink traversal for Autommit path: ${current}`, current);
            }
        } else {
            const error = result.error;
            if (isErrorCode(error, "ENOENT")) {
                if (allowMissingFinal && current === absolute) return false;
                return yield* pathFailure(`Autommit path does not exist: ${current}`, current);
            }
            return yield* pathError("Unable to inspect Autommit path", current, error);
        }
    }
    return true;
});

const makePaths = (commonDir: string): Paths => {
    const base = validateCommonDir(commonDir);
    const directory = join(base, AUTOMMIT_DIRECTORY);
    return {
        commonDir: base,
        directory,
        receipt: join(directory, RECEIPT_FILENAME),
        lock: join(directory, LOCK_FILENAME),
    };
};

const makePathsEffect = Effect.fn("makePaths")((commonDir: string) =>
    Effect.try({
        try: () => makePaths(commonDir),
        catch: (error) => pathError("Invalid Git commonDir", String(commonDir), error),
    }),
);

const ensureCommonDirectoryEffect = Effect.fn("ensureCommonDirectory")(function*(
    paths: Paths,
): Effect.fn.Return<void, AutommitPathError> {
    const noSymlink = yield* ensureNoSymlinkPathEffect(paths.commonDir, false, paths.commonDir);
    if (!noSymlink) {
        return yield* pathFailure(`Git commonDir does not exist: ${paths.commonDir}`, paths.commonDir);
    }
    const baseStats = yield* Effect.tryPromise({
        try: () => lstat(paths.commonDir),
        catch: (error) => pathError("Unable to inspect Git commonDir", paths.commonDir, error),
    });
    if (!baseStats.isDirectory()) {
        return yield* pathFailure(`Git commonDir is not a directory: ${paths.commonDir}`, paths.commonDir);
    }
});

const isUnsupportedWindowsDirectorySyncError = (error: unknown): boolean =>
    process.platform === "win32" && isErrorCode(error, "EPERM");

const syncDirectoryEffect = Effect.fn("syncDirectory")((directory: string) =>
    Effect.acquireUseRelease(
        Effect.tryPromise({
            try: () => open(directory, "r"),
            catch: (error) => pathError("Unable to open Autommit directory", directory, error),
        }),
        (handle) =>
            Effect.tryPromise({
                try: () => handle.sync(),
                catch: (error) => error,
            }).pipe(
                Effect.catchAll((error) =>
                    isUnsupportedWindowsDirectorySyncError(error)
                        ? Effect.void
                        : Effect.fail(pathError("Unable to sync Autommit directory", directory, error)),
                ),
            ),
        (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
    ),
);

const ensureAutommitDirectoryEffect = Effect.fn("ensureAutommitDirectory")(function*(
    paths: Paths,
): Effect.fn.Return<void, AutommitPathError> {
    yield* ensureCommonDirectoryEffect(paths);
    const created = yield* Effect.tryPromise({
        try: () => mkdir(paths.directory),
        catch: (error) => error,
    }).pipe(
        Effect.as(true),
        Effect.catchAll((error) =>
            isErrorCode(error, "EEXIST")
                ? Effect.succeed(false)
                : Effect.fail(pathError("Unable to create Autommit directory", paths.directory, error)),
        ),
    );

    if (created) yield* syncDirectoryEffect(paths.commonDir);

    const exists = yield* ensureNoSymlinkPathEffect(paths.directory, false, paths.commonDir);
    if (!exists) {
        return yield* pathFailure(`Autommit directory does not exist: ${paths.directory}`, paths.directory);
    }
    const directoryStats = yield* Effect.tryPromise({
        try: () => lstat(paths.directory),
        catch: (error) => pathError("Unable to inspect Autommit directory", paths.directory, error),
    });
    if (!directoryStats.isDirectory()) {
        return yield* pathFailure(`Autommit path is not a directory: ${paths.directory}`, paths.directory);
    }
});

const existingAutommitDirectoryEffect = Effect.fn("existingAutommitDirectory")(function*(
    paths: Paths,
): Effect.fn.Return<boolean, AutommitPathError> {
    const commonExists = yield* ensureNoSymlinkPathEffect(paths.commonDir, true, paths.commonDir);
    if (!commonExists) return false;
    const baseStats = yield* Effect.tryPromise({
        try: () => lstat(paths.commonDir),
        catch: (error) => pathError("Unable to inspect Git commonDir", paths.commonDir, error),
    });
    if (!baseStats.isDirectory()) {
        return yield* pathFailure(`Git commonDir is not a directory: ${paths.commonDir}`, paths.commonDir);
    }
    const dirExists = yield* ensureNoSymlinkPathEffect(paths.directory, true, paths.commonDir);
    if (!dirExists) return false;
    const directoryStats = yield* Effect.tryPromise({
        try: () => lstat(paths.directory),
        catch: (error) => pathError("Unable to inspect Autommit directory", paths.directory, error),
    });
    if (!directoryStats.isDirectory()) {
        return yield* pathFailure(`Autommit path is not a directory: ${paths.directory}`, paths.directory);
    }
    return true;
});

const validateString = (value: unknown, field: string): string => {
    if (
        typeof value !== "string" ||
        value.length === 0 ||
        value.length > MAX_STRING_LENGTH ||
        value.trim().length === 0 ||
        /[\u0000-\u001f\u007f]/u.test(value)
    ) {
        throw new AutommitReceiptError({
            message: `Invalid Autommit receipt: ${field} must be a non-empty bounded string.`,
        });
    }
    return value;
};

const isRecord = (value: unknown): value is JsonRecord =>
    typeof value === "object" && value !== null && !Array.isArray(value);

const hasExactKeys = (value: JsonRecord, keys: readonly string[]): boolean => {
    const ownKeys = Reflect.ownKeys(value);
    return ownKeys.length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
};

const validateReceiptValue = (value: unknown): Receipt => {
    if (!isRecord(value) || Object.getPrototypeOf(value) !== Object.prototype || !hasExactKeys(value, RECEIPT_KEYS)) {
        throw new AutommitReceiptError({
            message: "Invalid Autommit receipt: expected exactly version, state, ref, before, after, and indexTree.",
        });
    }
    if (value.version !== 1) {
        throw new AutommitReceiptError({ message: "Invalid Autommit receipt: version must be 1." });
    }
    if (typeof value.state !== "string" || !(RECEIPT_STATES as readonly string[]).includes(value.state)) {
        throw new AutommitReceiptError({
            message: "Invalid Autommit receipt: state must be prepared or committed.",
        });
    }
    return {
        version: 1,
        state: value.state as ReceiptState,
        ref: validateString(value.ref, "ref"),
        before: validateString(value.before, "before"),
        after: validateString(value.after, "after"),
        indexTree: validateString(value.indexTree, "indexTree"),
    };
};

const serializeReceipt = (receipt: Receipt): string => {
    const validated = validateReceiptValue(receipt);
    const serialized = `${JSON.stringify(validated)}\n`;
    if (Buffer.byteLength(serialized, "utf8") > MAX_JSON_BYTES) {
        throw new AutommitReceiptError({
            message: `Invalid Autommit receipt: serialized JSON exceeds ${MAX_JSON_BYTES} bytes.`,
        });
    }
    return serialized;
};

const decodeUtf8 = (buffer: Buffer, target: string): string => {
    try {
        return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    } catch (error) {
        throw pathError("Unable to decode Autommit JSON", target, error);
    }
};

const readBoundedTextEffect = Effect.fn("readBoundedText")((
    target: string,
    maxBytes: number,
) =>
    Effect.acquireUseRelease(
        Effect.tryPromise({
            try: () => open(target, "r"),
            catch: (error) => pathError("Unable to open Autommit file", target, error),
        }),
        (handle) =>
            Effect.tryPromise({
                try: async () => {
                    const buffer = Buffer.alloc(maxBytes + 1);
                    const result = await handle.read(buffer, 0, buffer.length, 0);
                    if (result.bytesRead > maxBytes) {
                        throw new AutommitReceiptError({
                            message: `Autommit file exceeds the ${maxBytes}-byte limit: ${target}`,
                        });
                    }
                    return decodeUtf8(buffer.subarray(0, result.bytesRead), target);
                },
                catch: (error) =>
                    error instanceof AutommitReceiptError || error instanceof AutommitPathError
                        ? error
                        : pathError("Unable to read Autommit file", target, error),
            }),
        (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
    ),
);

const existingRegularFileEffect = Effect.fn("existingRegularFile")(function*(
    target: string,
    kind: string,
    commonDir: string,
): Effect.fn.Return<boolean, AutommitPathError> {
    const exists = yield* ensureNoSymlinkPathEffect(target, true, commonDir);
    if (!exists) return false;
    const stats = yield* Effect.tryPromise({
        try: () => lstat(target),
        catch: (error) => pathError(`Unable to inspect Autommit ${kind}`, target, error),
    });
    if (stats.isSymbolicLink()) {
        return yield* pathFailure(`Refusing symlink traversal for Autommit ${kind}: ${target}`, target);
    }
    if (!stats.isFile()) {
        return yield* pathFailure(`Autommit ${kind} is not a regular file: ${target}`, target);
    }
    return true;
});

const parseJson = (text: string, target: string): unknown => {
    try {
        return JSON.parse(text) as unknown;
    } catch (error) {
        throw pathError("Invalid Autommit JSON", target, error);
    }
};

const readReceiptAtEffect = Effect.fn("readReceiptAt")(function*(
    paths: Paths,
): Effect.fn.Return<Receipt | null, AutommitPathError | AutommitReceiptError> {
    const dirExists = yield* existingAutommitDirectoryEffect(paths);
    if (!dirExists) return null;
    const fileExists = yield* existingRegularFileEffect(paths.receipt, "receipt", paths.commonDir);
    if (!fileExists) return null;

    const text = yield* readBoundedTextEffect(paths.receipt, MAX_JSON_BYTES);
    const receipt = yield* Effect.try({
        try: () => validateReceiptValue(parseJson(text, paths.receipt)),
        catch: (error) =>
            error instanceof AutommitPathError || error instanceof AutommitReceiptError
                ? error
                : new AutommitReceiptError({ message: String(error), cause: error }),
    });
    const stillPresent = yield* ensureNoSymlinkPathEffect(paths.receipt, false, paths.commonDir);
    if (!stillPresent) {
        return yield* new AutommitReceiptError({
            message: `Autommit receipt disappeared while reading: ${paths.receipt}`,
        });
    }
    return receipt;
});

export const readReceipt = (commonDir: string): Promise<Receipt | null> =>
    Effect.runPromise(makePathsEffect(commonDir).pipe(Effect.flatMap(readReceiptAtEffect)));

export const writeReceiptEffect = Effect.fn("writeReceipt")(function*(
    commonDir: string,
    receipt: Receipt,
): Effect.fn.Return<void, AutommitPathError | AutommitReceiptError> {
    const paths = yield* makePathsEffect(commonDir);
    const serialized = yield* Effect.try({
        try: () => serializeReceipt(receipt),
        catch: (error) => error instanceof AutommitReceiptError
            ? error
            : new AutommitReceiptError({ message: String(error), cause: error }),
    });
    yield* ensureAutommitDirectoryEffect(paths);
    yield* existingRegularFileEffect(paths.receipt, "receipt", paths.commonDir);

    const tempPath = join(paths.directory, `.${RECEIPT_FILENAME}.tmp-${makeToken()}`);

    yield* Effect.acquireUseRelease(
        Effect.succeed(tempPath),
        () =>
            Effect.gen(function*() {
                yield* Effect.acquireUseRelease(
                    Effect.tryPromise({
                        try: () => open(tempPath, "wx", 0o600),
                        catch: (error) => pathError("Unable to open Autommit receipt temp file", tempPath, error),
                    }),
                    (handle) =>
                        Effect.tryPromise({
                            try: async () => {
                                await handle.writeFile(serialized, "utf8");
                                await handle.sync();
                            },
                            catch: (error) => pathError("Unable to write Autommit receipt", paths.receipt, error),
                        }),
                    (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
                );
                yield* existingRegularFileEffect(paths.receipt, "receipt", paths.commonDir);
                yield* Effect.tryPromise({
                    try: () => rename(tempPath, paths.receipt),
                    catch: (error) => pathError("Unable to replace Autommit receipt", paths.receipt, error),
                });
                yield* syncDirectoryEffect(paths.directory);
            }),
        (path) => Effect.promise(() => unlink(path).catch(() => undefined)),
    );
});

export const writeReceipt = (commonDir: string, receipt: Receipt): Promise<void> =>
    Effect.runPromise(writeReceiptEffect(commonDir, receipt));

export const removeReceiptEffect = Effect.fn("removeReceipt")(function*(
    commonDir: string,
): Effect.fn.Return<void, AutommitPathError> {
    const paths = yield* makePathsEffect(commonDir);
    const dirExists = yield* existingAutommitDirectoryEffect(paths);
    if (!dirExists) return;
    const fileExists = yield* existingRegularFileEffect(paths.receipt, "receipt", paths.commonDir);
    if (!fileExists) return;

    yield* Effect.tryPromise({
        try: async () => {
            try {
                await unlink(paths.receipt);
            } catch (error) {
                if (!isErrorCode(error, "ENOENT")) throw error;
            }
        },
        catch: (error) => pathError("Unable to remove Autommit receipt", paths.receipt, error),
    });

    yield* syncDirectoryEffect(paths.directory);
});

export const removeReceipt = (commonDir: string): Promise<void> =>
    Effect.runPromise(removeReceiptEffect(commonDir));

let operationCounter = 0;

const makeToken = (): string => {
    operationCounter += 1;
    return `${process.pid}-${Date.now().toString(36)}-${operationCounter.toString(36)}-${Math.random().toString(36).slice(2)}`;
};

const lockJson = (owner: LockOwner): string => `${JSON.stringify(owner)}\n`;

const parseLockOwner = (value: unknown): LockOwner | null => {
    if (!isRecord(value) || Object.getPrototypeOf(value) !== Object.prototype || !hasExactKeys(value, LOCK_KEYS)) return null;
    if (
        typeof value.pid !== "number" ||
        !Number.isSafeInteger(value.pid) ||
        value.pid <= 0 ||
        typeof value.token !== "string" ||
        value.token.length === 0 ||
        value.token.length > MAX_STRING_LENGTH ||
        /[\u0000-\u001f\u007f]/u.test(value.token)
    ) {
        return null;
    }
    return { pid: value.pid, token: value.token };
};

const releaseOperationLockEffect = Effect.fn("releaseOperationLock")(function*(
    paths: Paths,
    owner: LockOwner,
): Effect.fn.Return<void, AutommitPathError> {
    const isFile = yield* existingRegularFileEffect(paths.lock, "operation lock", paths.commonDir);
    if (!isFile) return;

    const readAttempt = yield* readBoundedTextEffect(paths.lock, MAX_LOCK_BYTES).pipe(
        Effect.flatMap((text) =>
            Effect.try({
                try: () => parseLockOwner(parseJson(text, paths.lock)),
                catch: (error) =>
                    error instanceof AutommitPathError
                        ? error
                        : pathError("Invalid Autommit operation lock", paths.lock, error),
            }),
        ),
        Effect.orElseSucceed(() => null),
    );

    if (!readAttempt || readAttempt.pid !== owner.pid || readAttempt.token !== owner.token) return;

    const stillFile = yield* existingRegularFileEffect(paths.lock, "operation lock", paths.commonDir);
    if (!stillFile) return;

    yield* Effect.tryPromise({
        try: async () => {
            try {
                await unlink(paths.lock);
            } catch (error) {
                if (!isErrorCode(error, "ENOENT")) throw error;
            }
        },
        catch: (error) => pathError("Unable to release Autommit operation lock", paths.lock, error),
    });
});

export const withOperationLockEffect = Effect.fn("withOperationLock")(function*<T, E>(
    commonDir: string,
    effectFn: () => Effect.Effect<T, E>,
): Effect.fn.Return<T, AutommitTransactionError | E> {
        const paths = yield* makePathsEffect(commonDir);
        yield* ensureAutommitDirectoryEffect(paths);
        const owner: LockOwner = { pid: process.pid, token: makeToken() };
        const serialized = lockJson(owner);
        if (Buffer.byteLength(serialized, "utf8") > MAX_LOCK_BYTES) {
            return yield* new AutommitLockError({
                message: "Unable to acquire Autommit operation lock: lock metadata exceeds its size limit.",
            });
        }

        const lockHandle = yield* Effect.tryPromise({
            try: () => open(paths.lock, "wx", 0o600),
            catch: (cause) =>
                isErrorCode(cause, "EEXIST")
                    ? new AutommitLockError({
                        message: `Autommit operation already in progress (lock: ${paths.lock}). Inspect the lock's PID; stale locks are never removed automatically.`,
                    })
                    : new AutommitLockError({
                        message: `Unable to acquire Autommit operation lock: ${cause instanceof Error ? cause.message : String(cause)}`,
                        cause,
                    }),
        });

        yield* Effect.acquireUseRelease(
            Effect.succeed(lockHandle),
            (handle) =>
                Effect.tryPromise({
                    try: async () => {
                        await handle.writeFile(serialized, "utf8");
                        await handle.sync();
                    },
                    catch: (cause) => new AutommitLockError({
                        message: `Unable to write Autommit operation lock: ${cause instanceof Error ? cause.message : String(cause)}`,
                        cause,
                    }),
                }),
            (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
        ).pipe(
            Effect.catch((error) =>
                Effect.promise(() => unlink(paths.lock).catch(() => undefined)).pipe(
                    Effect.andThen(Effect.fail(error)),
                ),
            ),
        );

        return yield* Effect.acquireUseRelease(
            Effect.succeed(owner),
            () => effectFn(),
            (o) => releaseOperationLockEffect(paths, o),
        );
    });

export const withOperationLock = <T>(commonDir: string, fn: () => Promise<T>): Promise<T> =>
    Effect.runPromise(
        withOperationLockEffect(commonDir, () => Effect.tryPromise({
            try: fn,
            catch: (cause) => new AutommitOperationError({
                message: cause instanceof Error ? cause.message : String(cause),
                cause,
            }),
        })),
    );
