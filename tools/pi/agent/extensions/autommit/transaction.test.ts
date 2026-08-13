import { describe, expect, test } from "bun:test";
import {
    access,
    mkdir,
    mkdtemp,
    readFile,
    readlink,
    rm,
    symlink,
    writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
    consumeCompletedReceipt,
    preparedCommitTreeMatchesIndex,
    readReceipt,
    removeReceipt,
    withOperationLock,
    writeReceipt,
} from "./transaction.js";

const receipt = {
    version: 1 as const,
    state: "prepared" as const,
    ref: "refs/heads/main",
    before: "1111111111111111111111111111111111111111",
    after: "2222222222222222222222222222222222222222",
    indexTree: "3333333333333333333333333333333333333333",
};

const makeCommonDir = (): Promise<string> => mkdtemp(join(tmpdir(), "autommit-transaction-"));
const receiptPath = (commonDir: string): string => join(commonDir, "autommit", "receipt.json");
const lockPath = (commonDir: string): string => join(commonDir, "autommit", "operation.lock");

const isPresent = async (path: string): Promise<boolean> => {
    try {
        await access(path);
        return true;
    } catch {
        return false;
    }
};

describe("autommit receipt consumption", () => {
    test("consumes completed receipts and keeps prepared receipts", async () => {
        const commonDir = await makeCommonDir();
        try {
            const committedReceipt = { ...receipt, state: "committed" as const };
            await writeReceipt(commonDir, committedReceipt);
            expect(await consumeCompletedReceipt(commonDir, committedReceipt)).toBeNull();
            expect(await readReceipt(commonDir)).toBeNull();

            await writeReceipt(commonDir, receipt);
            expect(await consumeCompletedReceipt(commonDir, receipt)).toBe(receipt);
            expect(await readReceipt(commonDir)).toEqual(receipt);
        } finally {
            await rm(commonDir, { recursive: true, force: true });
        }
    });

    test("compares prepared commit trees against the staged index", () => {
        const tree = "4444444444444444444444444444444444444444";
        expect(preparedCommitTreeMatchesIndex(tree, tree)).toBe(true);
        expect(preparedCommitTreeMatchesIndex(tree, receipt.indexTree)).toBe(false);
    });
});

describe("autommit transaction metadata", () => {
    test("round trips receipts and removes them idempotently", async () => {
        const commonDir = await makeCommonDir();
        try {
            await writeReceipt(commonDir, receipt);
            await expect(readReceipt(commonDir)).resolves.toEqual(receipt);
            await removeReceipt(commonDir);
            await removeReceipt(commonDir);
            await expect(readReceipt(commonDir)).resolves.toBeNull();
        } finally {
            await rm(commonDir, { recursive: true, force: true });
        }
    });

    test("does not follow a receipt symlink", async () => {
        const commonDir = await makeCommonDir();
        const outsideDir = await makeCommonDir();
        try {
            await mkdir(join(commonDir, "autommit"), { recursive: true });
            const outsideReceipt = join(outsideDir, "receipt.json");
            await writeFile(outsideReceipt, JSON.stringify(receipt), "utf8");
            await symlink(outsideReceipt, receiptPath(commonDir));
            await expect(readReceipt(commonDir)).rejects.toThrow(/symlink|receipt/i);
            await expect(writeReceipt(commonDir, receipt)).rejects.toThrow(/symlink|receipt/i);
            await expect(removeReceipt(commonDir)).rejects.toThrow(/symlink|receipt/i);
            await expect(readlink(receiptPath(commonDir))).resolves.toBe(outsideReceipt);
            await expect(readFile(outsideReceipt, "utf8")).resolves.toBe(JSON.stringify(receipt));
        } finally {
            await rm(commonDir, { recursive: true, force: true });
            await rm(outsideDir, { recursive: true, force: true });
        }
    });

    test("serializes operations and releases the lock", async () => {
        const commonDir = await makeCommonDir();
        let release!: () => void;
        let entered!: () => void;
        const enteredPromise = new Promise<void>(resolve => {
            entered = resolve;
        });
        const releasePromise = new Promise<void>(resolve => {
            release = resolve;
        });
        const first = withOperationLock(commonDir, async () => {
            entered();
            await releasePromise;
            return "first";
        });
        try {
            await enteredPromise;
            const lock = JSON.parse(await readFile(lockPath(commonDir), "utf8")) as { pid: number; token: string };
            expect(lock.pid).toBe(process.pid);
            expect(lock.token).toEqual(expect.any(String));
            await expect(withOperationLock(commonDir, async () => "second")).rejects.toThrow(/lock/i);
            release();
            await expect(first).resolves.toBe("first");
            expect(await isPresent(lockPath(commonDir))).toBe(false);
        } finally {
            release();
            await first.catch(() => undefined);
            await rm(commonDir, { recursive: true, force: true });
        }
    });
});
