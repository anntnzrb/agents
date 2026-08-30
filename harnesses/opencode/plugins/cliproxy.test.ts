import { expect, test } from "bun:test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { mergeOpenCodeModels, type OpenCodeCatalogModel } from "./cliproxy.ts";

test("preserves fetched efforts and resolves the max policy", () => {
  const models = mergeOpenCodeModels(
    [catalogModel("go/deepseek-next", ["low", "high", "max", "ultra"])],
    {},
  );

  expect(models["go/deepseek-next"]).toMatchObject({
    reasoning: true,
    variants: {
      low: { reasoningEffort: "low" },
      high: { reasoningEffort: "high" },
      max: { reasoningEffort: "ultra" },
      ultra: { reasoningEffort: "ultra" },
    },
  });
});

test("preserves configured model options and variants", () => {
  const models = mergeOpenCodeModels([catalogModel("chatgpt/sol", ["low", "high"])], {
    "chatgpt/sol": {
      name: "Configured Sol",
      options: { textVerbosity: "low" },
      variants: {
        high: { reasoningEffort: "high", reasoningSummary: "detailed" },
        custom: { reasoningEffort: "low" },
      },
    },
    "local/custom": { name: "Local Custom" },
  });

  expect(models["chatgpt/sol"]).toMatchObject({
    name: "Configured Sol",
    options: { textVerbosity: "low" },
    variants: {
      low: { reasoningEffort: "low" },
      high: { reasoningEffort: "high", reasoningSummary: "detailed" },
      max: { reasoningEffort: "high" },
      custom: { reasoningEffort: "low" },
    },
  });
  expect(models["local/custom"]).toEqual({ name: "Local Custom" });
});

test("loads live catalog models through the installed runtime resolver", async () => {
  const home = await mkdtemp(join(tmpdir(), "opencode-cliproxy-plugin-test-"));
  try {
    const runtimeClientPath = join(
      home,
      ".config",
      "opencode",
      "node_modules",
      "@anntnzrb",
      "agentium",
      "dist",
      "runtime",
      "model-catalog-client.js",
    );
    const runnerPath = join(home, "run-plugin.ts");
    await mkdir(dirname(runtimeClientPath), { recursive: true });
    await writeFile(
      runtimeClientPath,
      `
export async function resolveLiveModelCatalog({ baseUrl }) {
  if (baseUrl !== "\${CLIPROXY_CLIENT_BASE_URL}") throw new Error("unexpected base URL: " + baseUrl);
  return [{
    id: "cmd/live",
    name: "Live",
    reasoning: true,
    reasoningEfforts: ["low", "high"],
    input: ["text"],
    cost: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 1000000,
    maxTokens: 64000,
  }];
}
`,
      "utf8",
    );
    await writeFile(
      runnerPath,
      `
import { CLIProxyCatalog } from ${JSON.stringify(
        `${pathToFileURL(join(import.meta.dir, "cliproxy.ts")).href}?run=${Date.now()}`,
      )};

const plugin = await CLIProxyCatalog();
const config = { provider: { cliproxy: {} } };
await plugin.config(config);
process.stdout.write(JSON.stringify(config.provider.cliproxy.models));
`,
      "utf8",
    );

    const child = spawn(process.execPath, [runnerPath], {
      cwd: home,
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
    expect(JSON.parse(stdout)).toMatchObject({
      "cmd/live": {
        name: "cmd — Live",
        reasoning: true,
        variants: {
          low: { reasoningEffort: "low" },
          high: { reasoningEffort: "high" },
          max: { reasoningEffort: "high" },
        },
        limit: { context: 1000000, output: 64000 },
      },
    });
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

function catalogModel(
  id: string,
  reasoningEfforts: OpenCodeCatalogModel["reasoningEfforts"],
): OpenCodeCatalogModel {
  return {
    id,
    name: id,
    reasoning: true,
    ...(reasoningEfforts ? { reasoningEfforts } : {}),
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 16384,
  };
}
