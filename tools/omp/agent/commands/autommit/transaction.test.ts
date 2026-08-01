import { describe, expect, test } from "bun:test";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readlink,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  readReceipt,
  removeReceipt,
  withOperationLock,
  writeReceipt,
} from "./transaction";

const receipt = {
  version: 1 as const,
  state: "prepared" as const,
  ref: "refs/heads/main",
  before: "1111111111111111111111111111111111111111",
  after: "2222222222222222222222222222222222222222",
  indexTree: "3333333333333333333333333333333333333333",
};

const makeCommonDir = (): Promise<string> =>
  mkdtemp(join(tmpdir(), "autommit-transaction-"));

const receiptPath = (commonDir: string): string =>
  join(commonDir, "autommit", "receipt.json");

const lockPath = (commonDir: string): string =>
  join(commonDir, "autommit", "operation.lock");

const isPresent = async (path: string): Promise<boolean> => {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
};

describe("Autommit transaction receipts", () => {
  test("round trips every version-one receipt state atomically", async () => {
    const commonDir = await makeCommonDir();
    try {
      for (const state of ["prepared", "committed", "undo-pending"] as const) {
        const expected = { ...receipt, state };
        await writeReceipt(commonDir, expected);
        await expect(readReceipt(commonDir)).resolves.toEqual(expected);
      }

      expect(await isPresent(receiptPath(commonDir))).toBe(true);
      expect((await readdir(join(commonDir, "autommit"))).sort()).toEqual([
        "receipt.json",
      ]);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("preserves receipt behavior for common directories with spaces", async () => {
    const parentDir = await makeCommonDir();
    const commonDir = join(parentDir, "git common dir");
    await mkdir(commonDir);
    try {
      await writeReceipt(commonDir, receipt);
      await expect(readReceipt(commonDir)).resolves.toEqual(receipt);
      await removeReceipt(commonDir);
      await expect(readReceipt(commonDir)).resolves.toBeNull();
    } finally {
      await rm(parentDir, { recursive: true, force: true });
    }
  });

  test("surfaces ordinary metadata directory failures", async () => {
    const commonDir = await makeCommonDir();
    try {
      await writeFile(join(commonDir, "autommit"), "not a directory", "utf8");
      await expect(writeReceipt(commonDir, receipt)).rejects.toThrow(/not a directory/i);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("rejects invalid receipt schemas", async () => {
    const commonDir = await makeCommonDir();
    try {
      await mkdir(join(commonDir, "autommit"), { recursive: true });
      await writeFile(
        receiptPath(commonDir),
        JSON.stringify({ ...receipt, state: "finished" }),
        "utf8",
      );

      await expect(readReceipt(commonDir)).rejects.toThrow(/receipt/i);
      await expect(
        writeReceipt(commonDir, { ...receipt, state: "finished" } as never),
      ).rejects.toThrow(/receipt/i);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("rejects oversized receipt JSON before parsing it", async () => {
    const commonDir = await makeCommonDir();
    try {
      await mkdir(join(commonDir, "autommit"), { recursive: true });
      await writeFile(
        receiptPath(commonDir),
        `${JSON.stringify(receipt).slice(0, -1)},"padding":"${"x".repeat(1_048_576)}"}`,
        "utf8",
      );

      await expect(readReceipt(commonDir)).rejects.toThrow(/receipt|size|large/i);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("rejects a tampered receipt with unknown fields", async () => {
    const commonDir = await makeCommonDir();
    try {
      await writeReceipt(commonDir, receipt);
      const tampered = JSON.parse(await readFile(receiptPath(commonDir), "utf8")) as Record<
        string,
        unknown
      >;
      tampered.tampered = true;
      await writeFile(receiptPath(commonDir), JSON.stringify(tampered), "utf8");

      await expect(readReceipt(commonDir)).rejects.toThrow(/receipt/i);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("does not follow a symlink at the receipt target", async () => {
    const commonDir = await makeCommonDir();
    const outsideDir = await makeCommonDir();
    try {
      await mkdir(join(commonDir, "autommit"), { recursive: true });
      const outsideReceipt = join(outsideDir, "outside-receipt.json");
      await writeFile(outsideReceipt, JSON.stringify(receipt), "utf8");
      await symlink(outsideReceipt, receiptPath(commonDir));

      await expect(readReceipt(commonDir)).rejects.toThrow(/symlink|receipt/i);
      await expect(writeReceipt(commonDir, receipt)).rejects.toThrow(/symlink|receipt/i);
      await expect(removeReceipt(commonDir)).rejects.toThrow(/symlink|receipt/i);
      expect(await readlink(receiptPath(commonDir))).toBe(outsideReceipt);
      expect(await readFile(outsideReceipt, "utf8")).toBe(JSON.stringify(receipt));
    } finally {
      await rm(commonDir, { recursive: true, force: true });
      await rm(outsideDir, { recursive: true, force: true });
    }
  });

  test("removal is idempotent and leaves no receipt", async () => {
    const commonDir = await makeCommonDir();
    try {
      await removeReceipt(commonDir);
      await writeReceipt(commonDir, receipt);
      await removeReceipt(commonDir);
      await removeReceipt(commonDir);

      await expect(readReceipt(commonDir)).resolves.toBeNull();
      expect(await isPresent(receiptPath(commonDir))).toBe(false);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });
});

describe("Autommit operation lock", () => {
  test("serializes operations and refuses an existing lock", async () => {
    const commonDir = await makeCommonDir();
    let unlock!: () => void;
    let entered!: () => void;
    const enteredOperation = new Promise<void>(resolve => {
      entered = resolve;
    });
    const holdOperation = new Promise<void>(resolve => {
      unlock = resolve;
    });
    let first: Promise<string> | undefined;
    try {
      first = withOperationLock(commonDir, async () => {
        entered();
        await holdOperation;
        return "first";
      });
      await enteredOperation;

      const lock = JSON.parse(await readFile(lockPath(commonDir), "utf8")) as {
        pid: number;
        token: string;
      };
      expect(lock.pid).toBe(process.pid);
      expect(lock.token).toEqual(expect.any(String));
      expect(lock.token.length).toBeGreaterThan(0);

      await expect(
        withOperationLock(commonDir, async () => "second"),
      ).rejects.toThrow(/lock/i);
      unlock();
      await expect(first).resolves.toBe("first");
      expect(await isPresent(lockPath(commonDir))).toBe(false);
    } finally {
      unlock();
      await first?.catch(() => undefined);
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("refuses a stale-looking lock without breaking it", async () => {
    const commonDir = await makeCommonDir();
    const staleLock = JSON.stringify({ pid: 999_999_999, token: "stale-token" });
    try {
      await mkdir(join(commonDir, "autommit"), { recursive: true });
      await writeFile(lockPath(commonDir), staleLock, "utf8");

      await expect(
        withOperationLock(commonDir, async () => "unexpected"),
      ).rejects.toThrow(/lock/i);
      await expect(readFile(lockPath(commonDir), "utf8")).resolves.toBe(staleLock);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("does not remove a lock replaced by another owner", async () => {
    const commonDir = await makeCommonDir();
    const replacement = JSON.stringify({ pid: process.pid, token: "replacement-token" });
    try {
      await withOperationLock(commonDir, async () => {
        await writeFile(lockPath(commonDir), replacement, "utf8");
      });

      await expect(readFile(lockPath(commonDir), "utf8")).resolves.toBe(replacement);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("releases the lock after a successful operation", async () => {
    const commonDir = await makeCommonDir();
    try {
      await expect(
        withOperationLock(commonDir, async () => "success"),
      ).resolves.toBe("success");
      await expect(
        withOperationLock(commonDir, async () => "again"),
      ).resolves.toBe("again");
      expect(await isPresent(lockPath(commonDir))).toBe(false);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });

  test("releases the lock after the operation throws", async () => {
    const commonDir = await makeCommonDir();
    try {
      await expect(
        withOperationLock(commonDir, async () => {
          throw new Error("operation failed");
        }),
      ).rejects.toThrow("operation failed");
      await expect(
        withOperationLock(commonDir, async () => "recovered"),
      ).resolves.toBe("recovered");
      expect(await isPresent(lockPath(commonDir))).toBe(false);
    } finally {
      await rm(commonDir, { recursive: true, force: true });
    }
  });
});
