import { afterEach, expect, test } from "bun:test";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { resolveSearchBinary } from "./search-binaries.ts";

const originalPath = process.env.PATH;
const originalAgentDir = process.env.PI_CODING_AGENT_DIR;

afterEach(() => {
  process.env.PATH = originalPath;
  if (originalAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
  else process.env.PI_CODING_AGENT_DIR = originalAgentDir;
});

test("resolves an executable asynchronously without a runSync defect", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "search-binary-"));
  const binaryName = process.platform === "win32" ? "rg.cmd" : "rg";
  const binaryPath = path.join(root, binaryName);
  try {
    await writeFile(binaryPath, process.platform === "win32" ? "@exit /b 0\r\n" : "#!/bin/sh\nexit 0\n", "utf8");
    if (process.platform !== "win32") await chmod(binaryPath, 0o755);
    process.env.PI_CODING_AGENT_DIR = path.join(root, "agent");
    process.env.PATH = root;

    await expect(resolveSearchBinary("rg")).resolves.toBe(binaryPath);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
