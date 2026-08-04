import { lstat, mkdir, open, rename, unlink, type FileHandle } from "node:fs/promises";
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

const isErrorCode = (error: unknown, code: string): boolean => {
    if (typeof error !== "object" || error === null || !("code" in error)) return false;
    return error.code === code;
};

const pathError = (operation: string, target: string, error: unknown): Error =>
    new Error(`${operation} ${target}: ${error instanceof Error ? error.message : String(error)}`);

const validateCommonDir = (commonDir: string): string => {
    if (typeof commonDir !== "string" || commonDir.length === 0 || commonDir.includes("\0")) {
        throw new TypeError("Git commonDir must be a non-empty path.");
    }
    return resolve(commonDir);
};

/**
 * Walks every Autommit-controlled component below the supplied commonDir
 * without allowing lstat/stat to follow a directory symlink. The commonDir
 * itself is checked, while components before it are pre-existing filesystem
 * paths intentionally outside this check (for example, macOS's /var
 * symlink).
 */
const ensureNoSymlinkPath = async (
    target: string,
    allowMissingFinal: boolean,
    commonDir: string,
): Promise<boolean> => {
    const absolute = resolve(target);
    const base = resolve(commonDir);
    const root = parse(absolute).root;
    const baseRoot = parse(base).root;
    const basePrefix = base.endsWith(sep) ? base : `${base}${sep}`;
    if (root !== baseRoot || (absolute !== base && !absolute.startsWith(basePrefix))) {
        throw new Error(`Autommit path is outside Git commonDir: ${absolute}`);
    }

    const relative = absolute === base ? "" : absolute.slice(base === baseRoot ? base.length : base.length + 1);
    const components = relative.split(sep).filter(Boolean);
    let current = base;

    for (const component of components.length === 0 ? [""] : components) {
        if (component) current = join(current, component);
        try {
            const stats = await lstat(current);
            if (stats.isSymbolicLink()) {
                throw new Error(`Refusing symlink traversal for Autommit path: ${current}`);
            }
        } catch (error) {
            if (isErrorCode(error, "ENOENT")) {
                if (allowMissingFinal && current === absolute) return false;
                throw new Error(`Autommit path does not exist: ${current}`);
            }
            if (error instanceof Error && error.message.startsWith("Refusing symlink traversal")) throw error;
            throw pathError("Unable to inspect Autommit path", current, error);
        }
    }
    return true;
};

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

const ensureCommonDirectory = async (paths: Paths): Promise<void> => {
    if (!(await ensureNoSymlinkPath(paths.commonDir, false, paths.commonDir))) {
        throw new Error(`Git commonDir does not exist: ${paths.commonDir}`);
    }
    const baseStats = await lstat(paths.commonDir).catch(error => {
        throw pathError("Unable to inspect Git commonDir", paths.commonDir, error);
    });
    if (!baseStats.isDirectory()) throw new Error(`Git commonDir is not a directory: ${paths.commonDir}`);
};

// Windows exposes directory handles but does not support flushing them: fsync reports EPERM.
const isUnsupportedWindowsDirectorySyncError = (error: unknown): boolean =>
    process.platform === "win32" && isErrorCode(error, "EPERM");

const syncDirectory = async (directory: string): Promise<void> => {
    let handle: FileHandle;
    try {
        handle = await open(directory, "r");
    } catch (error) {
        throw pathError("Unable to open Autommit directory", directory, error);
    }
    try {
        await handle.sync();
    } catch (error) {
        if (!isUnsupportedWindowsDirectorySyncError(error)) {
            throw pathError("Unable to sync Autommit directory", directory, error);
        }
    } finally {
        await handle.close();
    }
};

const ensureAutommitDirectory = async (paths: Paths): Promise<void> => {
    await ensureCommonDirectory(paths);
    let created = false;
    try {
        await mkdir(paths.directory);
        created = true;
    } catch (error) {
        if (!isErrorCode(error, "EEXIST")) throw pathError("Unable to create Autommit directory", paths.directory, error);
    }
    if (created) await syncDirectory(paths.commonDir);
    if (!(await ensureNoSymlinkPath(paths.directory, false, paths.commonDir))) {
        throw new Error(`Autommit directory does not exist: ${paths.directory}`);
    }
    const directoryStats = await lstat(paths.directory).catch(error => {
        throw pathError("Unable to inspect Autommit directory", paths.directory, error);
    });
    if (!directoryStats.isDirectory()) throw new Error(`Autommit path is not a directory: ${paths.directory}`);
};

const existingAutommitDirectory = async (paths: Paths): Promise<boolean> => {
    if (!(await ensureNoSymlinkPath(paths.commonDir, true, paths.commonDir))) return false;
    const baseStats = await lstat(paths.commonDir).catch(error => {
        throw pathError("Unable to inspect Git commonDir", paths.commonDir, error);
    });
    if (!baseStats.isDirectory()) throw new Error(`Git commonDir is not a directory: ${paths.commonDir}`);
    if (!(await ensureNoSymlinkPath(paths.directory, true, paths.commonDir))) return false;
    const directoryStats = await lstat(paths.directory).catch(error => {
        throw pathError("Unable to inspect Autommit directory", paths.directory, error);
    });
    if (!directoryStats.isDirectory()) throw new Error(`Autommit path is not a directory: ${paths.directory}`);
    return true;
};

const validateString = (value: unknown, field: string): string => {
    if (
        typeof value !== "string" ||
        value.length === 0 ||
        value.length > MAX_STRING_LENGTH ||
        value.trim().length === 0 ||
        /[\u0000-\u001f\u007f]/u.test(value)
    ) {
        throw new Error(`Invalid Autommit receipt: ${field} must be a non-empty bounded string.`);
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
        throw new Error("Invalid Autommit receipt: expected exactly version, state, ref, before, after, and indexTree.");
    }
    if (value.version !== 1) throw new Error("Invalid Autommit receipt: version must be 1.");
    if (typeof value.state !== "string" || !(RECEIPT_STATES as readonly string[]).includes(value.state)) {
        throw new Error("Invalid Autommit receipt: state must be prepared or committed.");
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
        throw new Error(`Invalid Autommit receipt: serialized JSON exceeds ${MAX_JSON_BYTES} bytes.`);
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

const readBoundedText = async (target: string, maxBytes: number): Promise<string> => {
    let handle: FileHandle | undefined;
    try {
        handle = await open(target, "r");
        const buffer = Buffer.alloc(maxBytes + 1);
        const result = await handle.read(buffer, 0, buffer.length, 0);
        if (result.bytesRead > maxBytes) {
            throw new Error(`Autommit file exceeds the ${maxBytes}-byte limit: ${target}`);
        }
        return decodeUtf8(buffer.subarray(0, result.bytesRead), target);
    } catch (error) {
        if (error instanceof Error && error.message.startsWith("Autommit file exceeds")) throw error;
        throw pathError("Unable to read Autommit file", target, error);
    } finally {
        if (handle) await handle.close().catch(() => {});
    }
};

const existingRegularFile = async (target: string, kind: string, commonDir: string): Promise<boolean> => {
    if (!(await ensureNoSymlinkPath(target, true, commonDir))) return false;
    const stats = await lstat(target).catch(error => {
        throw pathError(`Unable to inspect Autommit ${kind}`, target, error);
    });
    if (stats.isSymbolicLink()) throw new Error(`Refusing symlink traversal for Autommit ${kind}: ${target}`);
    if (!stats.isFile()) throw new Error(`Autommit ${kind} is not a regular file: ${target}`);
    return true;
};

const parseJson = (text: string, target: string): unknown => {
    try {
        return JSON.parse(text) as unknown;
    } catch (error) {
        throw pathError("Invalid Autommit JSON", target, error);
    }
};

const readReceiptAt = async (paths: Paths): Promise<Receipt | null> => {
    if (!(await existingAutommitDirectory(paths))) return null;
    if (!(await existingRegularFile(paths.receipt, "receipt", paths.commonDir))) return null;
    const text = await readBoundedText(paths.receipt, MAX_JSON_BYTES);
    const receipt = validateReceiptValue(parseJson(text, paths.receipt));
    if (!(await ensureNoSymlinkPath(paths.receipt, false, paths.commonDir))) {
        throw new Error(`Autommit receipt disappeared while reading: ${paths.receipt}`);
    }
    return receipt;
};

export const readReceipt = async (commonDir: string): Promise<Receipt | null> => readReceiptAt(makePaths(commonDir));

export const writeReceipt = async (commonDir: string, receipt: Receipt): Promise<void> => {
    const paths = makePaths(commonDir);
    const serialized = serializeReceipt(receipt);
    await ensureAutommitDirectory(paths);
    await existingRegularFile(paths.receipt, "receipt", paths.commonDir);

    const tempPath = join(paths.directory, `.${RECEIPT_FILENAME}.tmp-${makeToken()}`);
    let handle: FileHandle | undefined;
    try {
        handle = await open(tempPath, "wx", 0o600);
        await handle.writeFile(serialized, "utf8");
        await handle.sync();
        await handle.close();
        handle = undefined;
        await existingRegularFile(paths.receipt, "receipt", paths.commonDir);
        await rename(tempPath, paths.receipt);
        await syncDirectory(paths.directory);
    } catch (error) {
        throw pathError("Unable to write Autommit receipt", paths.receipt, error);
    } finally {
        if (handle) await handle.close().catch(() => {});
        await unlink(tempPath).catch(() => {});
    }
};

const makeToken = (): string => {
    operationCounter += 1;
    return `${process.pid}-${Date.now().toString(36)}-${operationCounter.toString(36)}-${Math.random().toString(36).slice(2)}`;
};

let operationCounter = 0;

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

const releaseOperationLock = async (paths: Paths, owner: LockOwner): Promise<void> => {
    if (!(await existingRegularFile(paths.lock, "operation lock", paths.commonDir))) return;
    let lock: LockOwner | null;
    try {
        lock = parseLockOwner(parseJson(await readBoundedText(paths.lock, MAX_LOCK_BYTES), paths.lock));
    } catch {
        return;
    }
    if (!lock || lock.pid !== owner.pid || lock.token !== owner.token) return;
    if (!(await existingRegularFile(paths.lock, "operation lock", paths.commonDir))) return;
    try {
        await unlink(paths.lock);
    } catch (error) {
        if (!isErrorCode(error, "ENOENT")) throw pathError("Unable to release Autommit operation lock", paths.lock, error);
    }
};

export const withOperationLock = async <T>(commonDir: string, fn: () => Promise<T>): Promise<T> => {
    const paths = makePaths(commonDir);
    await ensureAutommitDirectory(paths);
    const owner: LockOwner = { pid: process.pid, token: makeToken() };
    const serialized = lockJson(owner);
    if (Buffer.byteLength(serialized, "utf8") > MAX_LOCK_BYTES) {
        throw new Error("Unable to acquire Autommit operation lock: lock metadata exceeds its size limit.");
    }

    let handle: FileHandle | undefined;
    try {
        handle = await open(paths.lock, "wx", 0o600);
        await handle.writeFile(serialized, "utf8");
        await handle.sync();
        await handle.close();
        handle = undefined;
    } catch (error) {
        if (handle) await handle.close().catch(() => {});
        if (handle) await unlink(paths.lock).catch(() => {});
        if (isErrorCode(error, "EEXIST")) {
            throw new Error(
                `Autommit operation already in progress (lock: ${paths.lock}). Inspect the lock's PID; stale locks are never removed automatically.`,
            );
        }
        throw pathError("Unable to acquire Autommit operation lock", paths.lock, error);
    }

    try {
        return await fn();
    } finally {
        await releaseOperationLock(paths, owner);
    }
};
