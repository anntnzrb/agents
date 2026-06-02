import { describe, expect, test } from "bun:test";

import { runLineStreamingProcess } from "./line-process.js";

describe("runLineStreamingProcess", () => {
  test("collects parsed lines and stops at maxResults", async () => {
    const results = await runLineStreamingProcess<string>({
      command: process.execPath,
      args: ["-e", "console.log('a'); console.log('b'); console.log('c')"],
      maxResults: 2,
      missingBinaryMessage: "missing",
      parseLine: (line) => line,
    });

    expect(results).toEqual(["a", "b"]);
  });

  test("normalizes and filters empty lines", async () => {
    const results = await runLineStreamingProcess<string>({
      command: process.execPath,
      args: ["-e", "process.stdout.write('x\\r\\n\\n')"],
      maxResults: 5,
      skipEmptyLines: true,
      normalizeLine: (line) => line.replace(/\\r$/, ""),
      missingBinaryMessage: "missing",
      parseLine: (line) => line,
    });

    expect(results).toEqual(["x"]);
  });

  test("supports timeout", async () => {
    await expect(
      runLineStreamingProcess<string>({
        command: process.execPath,
        args: ["-e", "setTimeout(() => console.log('late'), 500)"],
        maxResults: 1,
        timeoutMs: 50,
        missingBinaryMessage: "missing",
        parseLine: (line) => line,
      }),
    ).rejects.toThrow(/timed out/);
  });

  test("supports abort signal", async () => {
    const controller = new AbortController();
    const pending = runLineStreamingProcess<string>({
      command: process.execPath,
      args: ["-e", "setTimeout(() => console.log('late'), 500)"],
      maxResults: 1,
      signal: controller.signal,
      missingBinaryMessage: "missing",
      parseLine: (line) => line,
    });
    controller.abort();
    await expect(pending).rejects.toThrow(/Operation aborted/);
  });
});
