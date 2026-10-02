import { expect, test } from "bun:test";
import "../scripts/offline-bun.ts";

test("CI rejects requests through the real fetch transport", async () => {
  await expect(fetch("https://example.invalid/")).rejects.toThrow("CI requires mocked HTTP transport");
});
