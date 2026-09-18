import { afterAll, expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Model } from "@opencode/plugin";
import { Schema } from "effect";
import discovery from "../plugins/cliproxy";
import tmap from "../plugins/tmap";

const cache = await mkdtemp(join(tmpdir(), "opencode-test-"));
const originalCache = process.env.XDG_CACHE_HOME;
process.env.XDG_CACHE_HOME = cache;
afterAll(async () => {
  if (originalCache === undefined) delete process.env.XDG_CACHE_HOME;
  else process.env.XDG_CACHE_HOME = originalCache;
  await rm(cache, { recursive: true, force: true });
});

test("discovery publishes v2 models and preserves inventory on gateway failure", async () => {
  let fail = false;
  const requests: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string) => {
    requests.push(url);
    if (url === "http://gateway/v1/models") {
      return fail ? new Response(null, { status: 503 }) : Response.json({ data: [
        { id: "gemini-3.8-flash-high", owned_by: "antigravity" },
        { id: "pool/vendor/unknown" },
        { id: null },
      ] });
    }
    if (url === "https://models.dev/api.json") return Response.json({ google: { models: {
      "gemini-3.8-flash": {
        name: "Gemini Flash", limit: { context: 1000000, output: 64000 },
        modalities: { input: ["text", "image"] }, cost: { input: 1, output: 2, cache_read: 0.1 },
        reasoning_options: [{ type: "effort", values: ["minimal", "low", "medium", "high"] }],
      },
    } } });
    throw new Error(`Unexpected URL: ${url}`);
  }) as typeof fetch;
  let models: readonly Model.Info[] = [];
  const transforms: Array<(editor: unknown) => void> = [];
  const editor = { add({ info, models: value }: { info: { id: string; settings?: { baseURL?: string } }; models: readonly Model.Info[] }) {
    expect(info.id).toBe("cliproxy");
    expect(info.settings?.baseURL).toBe("http://gateway/v1/");
    models = value;
  } };
  // Configured providers do not exist yet when external plugins set up in v2.0.7.
  const ctx = { options: { baseURL: "http://gateway/v1/" }, provider: {
    transform: async (callback: (editor: unknown) => void) => {
      transforms.push(callback);
      callback(editor);
    },
  } };
  try {
    await discovery.setup(ctx as never);
    expect(models).toHaveLength(2);
    for (const model of models) Schema.decodeUnknownSync(Model.Info)(model);
    expect(models[0]).toMatchObject({
      id: "gemini-3.8-flash-high", modelID: "gemini-3.8-flash-high", providerID: "cliproxy",
      name: "Gemini Flash (antigravity)", limit: { context: 1000000, output: 64000 },
      capabilities: { tools: true, input: ["text", "image"] },
      cost: [{ input: 1, output: 2, cache: { read: 0.1, write: 0 } }],
      variants: [
        { id: "minimal", settings: { reasoningEffort: "minimal" } },
        { id: "low", settings: { reasoningEffort: "low" } },
        { id: "medium", settings: { reasoningEffort: "medium" } },
        { id: "high", settings: { reasoningEffort: "high" } },
      ],
    });
    expect(models[1]).toMatchObject({ name: "pool/vendor/unknown (pool)", limit: { context: 200000, output: 32000 } });
    // Unknown ids without catalog data fall back to the Responses effort ladder so cycling works.
    expect(models[1].variants.map((variant) => variant.id)).toEqual(
      ["none", "minimal", "low", "medium", "high", "xhigh"],
    );
    const before = models;
    const requestCount = requests.length;
    transforms[0](editor);
    expect(models).toEqual(before);
    expect(requests).toHaveLength(requestCount); // Replaying transforms never performs I/O.
    fail = true;
    await discovery.setup(ctx as never);
    expect(models).toEqual(before);
    expect(transforms).toHaveLength(1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("continuation rewrites only the latest text-only dot in model context", async () => {
  let hook: (event: any) => void = () => { throw new Error("hook not registered"); };
  await tmap.setup({ session: { hook: async (name: string, callback: typeof hook) => {
    expect(name).toBe("context");
    hook = callback;
  } } } as never);
  const dot = { role: "user", content: [{ type: "text", text: " . " }] };
  const event = { messages: [dot, { role: "assistant", content: [] }], system: [] };
  hook(event);
  expect(event.messages[0].content[0].text).toBe("Continue.");
  expect(dot.content[0].text).toBe(" . "); // Persisted input is not mutated.
  expect(event.system).toEqual([expect.objectContaining({ type: "text", text: expect.stringContaining("MUST resume") })]);
  for (const messages of [
    [{ role: "user", content: [{ type: "text", text: "ordinary" }] }],
    [dot, { role: "user", content: [{ type: "text", text: "new task" }] }],
    [{ role: "user", content: [...dot.content, { type: "media", mediaType: "image/png", data: "x" }] }],
    [],
  ]) {
    const unchanged = { messages, system: [] };
    const snapshot = structuredClone(unchanged);
    hook(unchanged);
    expect(unchanged).toEqual(snapshot);
  }
});
