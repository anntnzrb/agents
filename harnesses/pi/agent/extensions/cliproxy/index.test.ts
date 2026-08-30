import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

test("resolves the live catalog asynchronously and registers Pi models", async () => {
  const home = await mkdtemp(join(tmpdir(), "pi-cliproxy-extension-test-"));

  try {
    const runtimeClientPath = join(
      home,
      ".local",
      "share",
      "agents",
      "sync-current",
      "src",
      "runtime",
      "model-catalog-client.ts",
    );
    const catalogPath = join(
      home,
      ".local",
      "share",
      "agents",
      "model-catalog",
      "catalog.json",
    );
    const runnerPath = join(home, "run-extension.ts");
    await mkdir(dirname(runtimeClientPath), { recursive: true });
    await mkdir(dirname(catalogPath), { recursive: true });
    await writeFile(
      runtimeClientPath,
      `
import { readFile } from "node:fs/promises";

export async function resolveLiveModelCatalog({ catalogPath, baseUrl }) {
  if (baseUrl !== "\${CLIPROXY_CLIENT_BASE_URL}") {
    throw new Error("unexpected base URL: " + baseUrl);
  }
  return JSON.parse(await readFile(catalogPath, "utf8")).models;
}
`,
      "utf8",
    );
    await writeFile(
      catalogPath,
      JSON.stringify({
        version: 1,
        models: [
          {
            id: "cliproxy/example",
            name: "Example",
            reasoning: true,
            reasoningEfforts: ["low", "ultra"],
            input: ["text", "image"],
            cost: { input: 1, output: 2, cacheRead: 0.1, cacheWrite: 0 },
            contextWindow: 128000,
            maxTokens: 32000,
          },
          {
            id: "cliproxy/plain",
            name: "Plain",
            reasoning: false,
            input: ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 64000,
            maxTokens: 8192,
          },
        ],
      }),
      "utf8",
    );
    await writeFile(
      runnerPath,
      `
import cliproxy from ${JSON.stringify(
        `${pathToFileURL(join(process.cwd(), "harnesses/pi/agent/extensions/cliproxy/index.ts")).href}?run=${Date.now()}`,
      )};

const registered = [];
await cliproxy({
  registerProvider(name, config) {
    registered.push({ name, config });
  },
});
process.stdout.write(JSON.stringify(registered[0]));
`,
      "utf8",
    );

    const child = spawn(process.execPath, [runnerPath], {
      env: { ...process.env, HOME: home },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    const [exitCode] = (await once(child, "close")) as [number | null];

    expect({ exitCode, stderr }).toEqual({ exitCode: 0, stderr: "" });
    expect(JSON.parse(stdout)).toEqual({
      name: "cliproxy",
      config: {
        name: "CLIProxyAPI",
        baseUrl: "${CLIPROXY_CLIENT_BASE_URL}",
        apiKey: "keyless",
        api: "openai-responses",
        models: [
          {
            id: "cliproxy/example",
            name: "cliproxy — Example",
            reasoning: true,
            thinkingLevelMap: {
              off: null,
              minimal: null,
              low: "low",
              medium: null,
              high: null,
              xhigh: null,
              max: "ultra",
            },
            input: ["text", "image"],
            cost: { input: 1, output: 2, cacheRead: 0.1, cacheWrite: 0 },
            contextWindow: 128000,
            maxTokens: 32000,
          },
          {
            id: "cliproxy/plain",
            name: "cliproxy — Plain",
            reasoning: false,
            input: ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 64000,
            maxTokens: 8192,
          },
        ],
      },
    });
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});
