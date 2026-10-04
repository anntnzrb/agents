import { afterEach, expect, test } from "bun:test";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { access } from "node:fs/promises";
import bg, { middle } from "./index.ts";

const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
// Waits for an asynchronous effect with a generous deadline, so slow runners do not flake.
async function until(ready: () => boolean, ms = 10000) {
  const deadline = Date.now() + ms;
  while (!ready() && Date.now() < deadline) await pause(20);
}
const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0)) await cleanup(); });
function load(settings = {}, mode = "rpc", hasUI = true) {
  const tools = new Map<string, ToolDefinition>();
  const messages: Array<{ content: string; options: unknown }> = [];
  let shutdown = async () => {};
  bg({
    getSettings: () => ({ bg: { thresholdMs: 40, maxJobMs: 5000, ...settings } }),
    registerTool: (tool: ToolDefinition) => tools.set(tool.name, tool),
    on: (name: string, callback: () => Promise<void>) => { if (name === "session_shutdown") shutdown = callback; },
    sendMessage: (message: { content: string }, options: unknown) => messages.push({ content: message.content, options }),
  } as unknown as ExtensionAPI);
  cleanups.push(() => shutdown());
  const ctx = { cwd: process.cwd(), mode, hasUI, sessionManager: { getSessionId: () => "test", getSessionFile: () => undefined } } as unknown as ExtensionContext;
  const run = (name: string, args: unknown, signal?: AbortSignal) => tools.get(name)!.execute("test", args, signal, undefined, ctx);
  const bash = (command: string, background = false, signal?: AbortSignal, timeout?: number) => run("bash", { command, background, timeout }, signal);
  const jobs = (action: string, id?: string, extra = {}, signal?: AbortSignal) => run("jobs", { action, id, ...extra }, signal);
  const text = (r: Awaited<ReturnType<typeof run>>) => r.content.map(c => c.type === "text" ? c.text : "").join("");
  const id = (r: Awaited<ReturnType<typeof run>>) => text(r).match(/bg-\d+/)![0];
  return { bash, jobs, text, id, messages, shutdown: () => shutdown() };
}

test("threshold backgrounds, streams to disk, and delivers automatically", async () => {
  const h = load(); const start = Date.now();
  const r = await h.bash("printf start; sleep 0.2; printf end");
  expect(Date.now() - start).toBeLessThan(5000);
  expect(h.text(r)).not.toContain("end");
  expect(h.text(r)).toContain("polling is unnecessary");
  expect(h.text(r)).toContain("start");
  await until(() => h.messages.length > 0);
  expect(h.messages).toHaveLength(1);
  expect(h.messages[0].content).toContain("startend");
  expect(h.messages[0].options).toEqual({ deliverAs: "followUp", triggerTurn: true });
});
test("fast command preserves built-in shape and output", async () => {
  const h = load(); const r = await h.bash("printf fast");
  expect(h.text(r)).toBe("fast");
  expect(r.structuredContent).toMatchObject({ output: "fast", exit_code: 0, truncated: false });
  expect(r.details).toBeUndefined();
});
test("coalesces exits", async () => {
  const h = load(); await h.bash("sleep 0.1; echo one", true); await h.bash("sleep 0.2; echo two", true);
  await until(() => h.messages.length > 0); await pause(1200); expect(h.messages).toHaveLength(1);
  expect(h.messages[0].content).toContain("one"); expect(h.messages[0].content).toContain("two");
});
test("SIGKILL is 137, not success", async () => {
  const h = load(); const r = await h.bash("sleep 0.1; kill -KILL $$", true);
  const done = await h.jobs("wait", h.id(r)); expect(h.text(done)).toContain("exit 137");
});
test("offset reads return only new bytes", async () => {
  const h = load(); const r = await h.bash("printf abc; sleep 0.3; printf def", true); const id = h.id(r);
  let first = await h.jobs("output", id);
  for (const end = Date.now() + 10000; !h.text(first).includes("abc") && Date.now() < end; first = await h.jobs("output", id)) await pause(20);
  expect(first.details).toMatchObject({ offset: 3 }); expect(h.text(first)).toContain("abc");
  await h.jobs("wait", id); const second = await h.jobs("output", id, { offset: 3 });
  expect(second.details).toMatchObject({ offset: 6 }); expect(h.text(second)).toContain("def"); expect(h.text(second)).not.toContain("abc");
});
const tree = `bash -c 'sleep 20 & echo $!; wait' & echo $!; wait`;
async function pids(h: ReturnType<typeof load>, id: string) {
  let found: number[] = [];
  for (const end = Date.now() + 10000; found.length < 2 && Date.now() < end; await pause(20)) found = (h.text(await h.jobs("output", id)).match(/^\d+$/gm) ?? []).map(Number);
  return found;
}
function alive(pid: number) { try { process.kill(pid, 0); return true; } catch { return false; } }
async function gone(pids: number[]) { await until(() => pids.every(pid => !alive(pid))); pids.forEach(pid => expect(alive(pid)).toBe(false)); }
test("kill terminates child and grandchild process group", async () => {
  const h = load(); const id = h.id(await h.bash(tree, true)); const children = await pids(h, id);
  expect(children).toHaveLength(2); await h.jobs("kill", id); await gone(children);
});
test("wait consumes without duplicate follow-up", async () => {
  const h = load(); const id = h.id(await h.bash("sleep 0.1; echo consumed", true));
  expect(h.text(await h.jobs("wait", id))).toContain("consumed"); await pause(1200); expect(h.messages).toHaveLength(0);
});
test("aborted wait preserves undelivered result", async () => {
  const h = load(); const id = h.id(await h.bash("echo retained", true)); await pause(100);
  const abort = new AbortController(); abort.abort();
  await expect(h.jobs("wait", id, {}, abort.signal)).rejects.toThrow();
  await until(() => h.messages.length > 0); expect(h.messages).toHaveLength(1); expect(h.messages[0].content).toContain("retained");
});
test("shutdown is idempotent, kills everything and removes logs", async () => {
  const h = load(); const r = await h.bash(tree, true); const children = await pids(h, h.id(r));
  const path = h.text(r).match(/Log: (\S+)/)![1]; await access(path);
  await h.shutdown(); await h.shutdown(); await gone(children); await expect(access(path)).rejects.toThrow();
});
test("hard maximum kills the job", async () => {
  const h = load({ maxJobMs: 100 }); const id = h.id(await h.bash("echo $$; exec sleep 20", true));
  const r = await h.jobs("wait", id); expect(h.text(r)).toContain("exit 137");
  await gone([Number(h.text(r).match(/^\d+$/m)![0])]);
});
test("print mode passes through and rejects explicit background", async () => {
  const h = load({}, "print", false); const start = Date.now();
  expect(h.text(await h.bash("sleep 0.1; echo print"))).toBe("print\n"); expect(Date.now() - start).toBeGreaterThan(90);
  await expect(h.bash("echo nope", true)).rejects.toThrow("unavailable");
});
test("foreground sleep rejection and abort", async () => {
  const h = load(); await expect(h.bash("sleep 5")).rejects.toThrow("jobs wait");
  const abort = new AbortController(); const pending = h.bash("echo $$; exec sleep 20", false, abort.signal);
  setTimeout(() => abort.abort(), 10); await expect(pending).rejects.toThrow("Command aborted");
});
test("middle truncation preserves both ends and exact omission counts", () => {
  const output = "head" + "x".repeat(100000) + "tail";
  const result = middle(output, 1000, 20);
  expect(result.startsWith("head")).toBe(true); expect(result.endsWith("tail")).toBe(true);
  expect(result).toContain("Omitted 99008 bytes, 0 newline characters");
  const lines = Array.from({ length: 100 }, (_, i) => `line${i}`).join("\n");
  const shortened = middle(lines, 10000, 10);
  expect(shortened).toContain("91 newline characters");
  expect(shortened).toContain("line0"); expect(shortened).toContain("line99");
});
test("wait any, timeout and in-flight abort preserve delivery", async () => {
  const h = load(); const id = h.id(await h.bash("sleep 0.2; echo any", true));
  expect(h.text(await h.jobs("wait", undefined, { timeout: 0.01 }))).toContain("timed out");
  const abort = new AbortController(); const wait = h.jobs("wait", id, {}, abort.signal);
  setTimeout(() => abort.abort(), 20); await expect(wait).rejects.toThrow("aborted");
  expect(h.text(await h.jobs("wait"))).toContain("any");
  await pause(1200); expect(h.messages).toHaveLength(0);
});
test("capacity falls back to foreground, including explicit background", async () => {
  const h = load();
  const started = await Promise.all(Array.from({ length: 8 }, () => h.bash("sleep 0.5", true)));
  expect(new Set(started.map(h.id)).size).toBe(8);
  const start = Date.now(); const r = await h.bash("sleep 0.1; echo capacity", true);
  expect(h.text(r)).toBe("capacity\n"); expect(Date.now() - start).toBeGreaterThan(90);
});
test("signal and timeout foreground failures preserve built-in behavior", async () => {
  const h = load({ thresholdMs: 500 });
  const result = await h.bash("kill -KILL $$"); expect(result.isError).toBe(true);
  expect(result.structuredContent).toMatchObject({ exit_code: 137 });
  await expect(h.bash("exec sleep 20", false, undefined, 0.03)).rejects.toThrow("Command timed out after 0.03 seconds");
  await expect(h.bash("echo nope", false, undefined, -1)).rejects.toThrow("Invalid timeout");
  await expect(h.jobs("output", "missing")).rejects.toThrow("Unknown");
});
