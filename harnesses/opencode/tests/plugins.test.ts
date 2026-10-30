import { expect, jest, test } from "bun:test";
import { Model } from "@opencode/plugin";
// Deliberately undeclared: this resolves to the single `effect` copy that `@opencode/plugin`
// installs. Declaring a version here installs a second copy whenever the two disagree, and a
// second copy owns a different Schema class, so decoding an @opencode schema with it fails.
import { Schema } from "effect";
import discovery from "../plugins/cliproxy";
import tmap from "../plugins/tmap";
import autobg from "../plugins/autobg/tui";

const flush = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
};

const catalogModel = (id: string, fields: Partial<Model.Info>): Model.Info => ({
  ...Model.Info.default("google" as never, id as never),
  ...fields,
});

test("discovery enriches gateway models from the models.dev provider records", async () => {
  jest.useFakeTimers();
  let down = true;
  let gateway: Array<{ id: unknown; owned_by?: string }> = [
    { id: "gemini-3.8-flash-high", owned_by: "antigravity" },
    { id: "pool/vendor/unknown" },
    { id: null },
  ];
  const requests: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string) => {
    requests.push(url);
    if (url !== "http://gateway/v1/models") throw new Error(`Unexpected URL: ${url}`);
    return down ? new Response(null, { status: 503 }) : Response.json({ data: gateway });
  }) as typeof fetch;
  const flash = catalogModel("gemini-3.8-flash", {
    name: "Gemini Flash",
    limit: { context: 1000000, output: 64000 },
    capabilities: { tools: true, input: ["text", "image"], output: ["text"] },
    cost: [{ input: 1, output: 2, cache: { read: 0.1, write: 0 } }] as never,
    variants: ["minimal", "low", "medium", "high"].map((id) => ({ id: id as never, settings: { thinkingLevel: id } })),
  });
  const narrow = catalogModel("gemini-3.8-flash", { name: "Narrow", limit: { context: 1000, output: 100 } });
  const records = [
    { provider: { id: "google" }, models: new Map([["gemini-3.8-flash", flash]]) },
    { provider: { id: "other" }, models: new Map([["vendor/gemini-3.8-flash", narrow]]) },
  ];
  let models: readonly Model.Info[] = [];
  let adds = 0;
  const transforms: Array<(editor: unknown) => void> = [];
  const editor = {
    list: () => records,
    add({ info, models: value }: { info: { id: string; settings?: { baseURL?: string } }; models: readonly Model.Info[] }) {
      expect(info.id).toBe("cliproxy");
      expect(info.settings?.baseURL).toBe("http://gateway/v1/");
      adds++;
      models = value;
    },
  };
  let reloads = 0;
  const ctx = { options: { baseURL: "http://gateway/v1/" }, provider: {
    transform: async (callback: (editor: unknown) => void) => {
      transforms.push(callback);
      callback(editor);
    },
    reload: async () => {
      reloads++;
      for (const transform of transforms) transform(editor);
    },
  } };
  const cleanup = await discovery.setup(ctx as never);
  try {
    expect(adds).toBe(0); // A gateway outage at boot publishes nothing.
    down = false;
    jest.advanceTimersByTime(5 * 60 * 1000);
    await flush();
    expect(reloads).toBe(1);
    expect(models).toHaveLength(2);
    for (const model of models) Schema.decodeUnknownSync(Model.Info)(model);
    expect(models[0]).toMatchObject({
      id: "gemini-3.8-flash-high", modelID: "gemini-3.8-flash-high", providerID: "cliproxy",
      name: "Gemini Flash (antigravity)", limit: { context: 1000000, output: 64000 },
      capabilities: { tools: true, input: ["text", "image"], output: ["text"] },
      cost: [{ input: 1, output: 2, cache: { read: 0.1, write: 0 } }],
      variants: [
        { id: "minimal", settings: { reasoningEffort: "minimal", reasoningSummary: "auto" } },
        { id: "low", settings: { reasoningEffort: "low" } },
        { id: "medium", settings: { reasoningEffort: "medium" } },
        { id: "high", settings: { reasoningEffort: "high" } },
      ],
    });
    expect(models[0].variants[0].settings).not.toHaveProperty("thinkingLevel");
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
    jest.advanceTimersByTime(5 * 60 * 1000);
    await flush();
    expect(reloads).toBe(1); // An unchanged inventory does not reload providers.
    down = true;
    jest.advanceTimersByTime(5 * 60 * 1000);
    await flush();
    expect(reloads).toBe(1); // A failed refresh keeps the last inventory.
    expect(models).toEqual(before);
    down = false;
    gateway = [{ id: "gemini-3.8-flash-high", owned_by: "antigravity" }];
    jest.advanceTimersByTime(5 * 60 * 1000);
    await flush();
    expect(reloads).toBe(2);
    expect(models.map((model) => model.id)).toEqual(["gemini-3.8-flash-high"]);
    expect(transforms).toHaveLength(1);
    (cleanup as () => void)();
    const count = requests.length;
    jest.advanceTimersByTime(5 * 60 * 1000);
    await flush();
    expect(requests).toHaveLength(count); // Cleanup stops the refresh timer.
  } finally {
    (cleanup as () => void)();
    jest.useRealTimers();
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

test("autobg backgrounds an open session whose tool call outlives the threshold", async () => {
  jest.useFakeTimers();
  const handlers = new Map<string, (event: any) => void>();
  const backgrounded: string[] = [];
  let tabs = [{ sessionID: "tab" }, { sessionID: "unknown" }];
  let route = "open";
  const cleanup = await autobg.setup({
    data: {
      on: (type: string, handler: (event: any) => void) => {
        handlers.set(type, handler);
        return () => handlers.delete(type);
      },
      session: {
        get: (id: string) => id === "unknown" ? undefined : id === "child" ? { parentID: "open" } : {},
        root: (id: string) => id === "child" ? "open" : id,
      },
    },
    ui: { router: { current: () => ({ type: "session", sessionID: route }) }, tabs: { list: () => tabs } },
    client: { session: { background: async ({ sessionID }: { sessionID: string }) => { backgrounded.push(sessionID); } } },
  } as never);
  const call = (sessionID: string, id: string, executed = false) =>
    handlers.get("session.tool.called")!({ data: { sessionID, id, executed } });
  try {
    call("open", "fast");
    handlers.get("session.tool.success")!({ data: { sessionID: "open", id: "fast" } });
    call("open", "failed");
    handlers.get("session.tool.failed")!({ data: { sessionID: "open", id: "failed" } });
    call("headless", "slow");
    call("unknown", "slow");
    call("open", "hosted", true);
    call("open", "slow");
    call("tab", "slow");
    jest.advanceTimersByTime(4999);
    expect(backgrounded).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(backgrounded).toEqual(["open", "tab"]);
    tabs = [];
    route = "child";
    call("tab", "later");
    call("child", "slow");
    jest.advanceTimersByTime(5000);
    expect(backgrounded).toEqual(["open", "tab"]);
    call("open", "viewing-child");
    jest.advanceTimersByTime(5000);
    expect(backgrounded).toEqual(["open", "tab", "open"]);
    call("open", "disposed");
  } finally {
    (cleanup as () => void)();
    jest.advanceTimersByTime(5000);
    jest.useRealTimers();
  }
  expect(backgrounded).toEqual(["open", "tab", "open"]);
  expect(handlers.size).toBe(0);
});
