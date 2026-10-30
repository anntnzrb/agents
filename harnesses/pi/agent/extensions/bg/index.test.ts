import { afterEach, expect, setDefaultTimeout, test } from "bun:test";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import bg, { middle } from "./index.ts";

// Above the 10 s `until` deadline plus fixed pauses, so slow runners fail on assertions, not the runner clock.
setDefaultTimeout(30000);
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
// Waits for an asynchronous effect with a generous deadline, so slow runners do not flake.
async function until(ready: () => boolean, ms = 10000) {
  const deadline = Date.now() + ms;
  while (!ready() && Date.now() < deadline) await pause(20);
}
const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0)) await cleanup(); });
function load(settings: Record<string, unknown> | null = {}, mode = "rpc", hasUI = true) {
  const tools = new Map<string, ToolDefinition>();
  const messages: Array<{ content: string; options: unknown }> = [];
  let shutdown = async () => {};
  const handlers = new Map<string, () => unknown>();
  bg({
    getSettings: () => (settings === null ? {} : { bg: { thresholdMs: 40, maxJobMs: 5000, ...settings } }),
    registerTool: (tool: ToolDefinition) => tools.set(tool.name, tool),
    on: (name: string, callback: () => Promise<void>) => { handlers.set(name, callback); if (name === "session_shutdown") shutdown = callback; },
    sendMessage: (message: { content: string }, options: unknown) => messages.push({ content: message.content, options }),
  } as unknown as ExtensionAPI);
  cleanups.push(() => shutdown());
  const pending = { value: false };
  const ctx = { cwd: process.cwd(), mode, hasUI, hasPendingMessages: () => pending.value, sessionManager: { getSessionId: () => "test", getSessionFile: () => undefined } } as unknown as ExtensionContext;
  const run = (name: string, args: unknown, signal?: AbortSignal, callId = "test") => tools.get(name)!.execute(callId, args, signal, undefined, ctx);
  const bash = (command: string, background = false, signal?: AbortSignal, timeout?: number) => run("bash", { command, background, timeout }, signal);
  const jobs = (action: string, id?: string, extra = {}, signal?: AbortSignal) => run("jobs", { action, id, ...extra }, signal);
  const text = (r: Awaited<ReturnType<typeof run>>) => r.content.map(c => c.type === "text" ? c.text : "").join("");
  const id = (r: Awaited<ReturnType<typeof run>>) => text(r).match(/bg-\d+/)![0];
  const emit = async (name: string) => { await handlers.get(name)?.(); };
  return { run, bash, jobs, text, id, messages, emit, pending, shutdown: () => shutdown() };
}

test("threshold backgrounds, streams to disk, and delivers automatically", async () => {
  const h = load(); const start = Date.now();
  const r = await h.bash("printf start; sleep 0.2; printf end");
  expect(Date.now() - start).toBeLessThan(5000);
  expect(h.text(r)).not.toContain("startend");
  expect(h.text(r)).toContain("do not poll");
  expect(h.text(r)).toContain("jobs kill");
  expect(h.text(r)).toContain("start");
  await until(() => h.messages.length > 0);
  expect(h.messages).toHaveLength(1);
  expect(h.messages[0].content).toContain("startend");
  expect(h.messages[0].options).toEqual({ deliverAs: "steer", triggerTurn: true });
});
test("defaults to a 5 second threshold when settings omit bg", async () => {
  const h = load(null); const start = Date.now();
  const fast = await h.bash("sleep 4; printf fg");
  expect(h.text(fast)).toBe("fg");
  const r = await h.bash("echo $$; sleep 8; printf late");
  expect(h.text(r)).toMatch(/Still running after 5s with \d+ bytes of output/);
  expect(h.text(r)).toContain("jobs kill");
  expect(Date.now() - start).toBeLessThan(11000);
  await h.jobs("kill", h.id(r));
}, 20000);
test("user threshold setting overrides the default", async () => {
  const h = load({ thresholdMs: 100 }); const start = Date.now();
  const r = await h.bash("sleep 1; printf late");
  expect(h.text(r)).toContain("moved to the background");
  expect(Date.now() - start).toBeLessThan(900);
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
  const timedOut = h.text(await h.jobs("wait", undefined, { timeout: 0.01 }));
  expect(timedOut).toContain("timed out"); expect(timedOut).toMatch(new RegExp(`${id}: running \\d+s, 0 bytes of output`));
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
test("completions during a run steer into it once, without waiting for the run to settle", async () => {
  const h = load(); await h.emit("agent_start");
  await h.bash("echo live", true);
  await until(() => h.messages.length > 0); await pause(1200);
  expect(h.messages).toHaveLength(1); expect(h.messages[0].content).toContain("live");
  expect(h.messages[0].options).toEqual({ deliverAs: "steer", triggerTurn: true });
});
test("a result read by wait is never delivered again, and a delivered result is not waited on", async () => {
  const h = load();
  const id = h.id(await h.bash("sleep 0.2; echo once", true));
  expect(h.text(await h.jobs("wait", id))).toContain("once");
  await pause(1500); expect(h.messages).toHaveLength(0);
  const other = h.id(await h.bash("echo pushed", true));
  await until(() => h.messages.length > 0);
  expect(h.text(await h.jobs("wait", other))).toContain("already finished");
});
test("list reports runtime, log size, and command for judging a running job", async () => {
  const h = load(); const id = h.id(await h.bash("echo noisy; exec sleep 20", true));
  await pause(200);
  const listed = h.text(await h.jobs("list"));
  expect(listed).toMatch(new RegExp(`${id}: running \\d+s, 6 bytes of output, "echo noisy; exec sleep 20"`));
  await h.jobs("kill", id);
});
test("nested tool calls stay in the foreground", async () => {
  const h = load({ thresholdMs: 50 }); const start = Date.now();
  const r = await h.run("bash", { command: "sleep 0.3; printf nested" }, undefined, "parent/1");
  expect(h.text(r)).toBe("nested"); expect(Date.now() - start).toBeGreaterThan(250);
  await expect(h.run("bash", { command: "echo x", background: true }, undefined, "parent/2")).rejects.toThrow("unavailable");
});
test("a job stopped with jobs kill is not delivered", async () => {
  const h = load(); const id = h.id(await h.bash("exec sleep 20", true));
  await h.jobs("kill", id); await pause(1500);
  expect(h.messages).toHaveLength(0);
});
test("wait returns as soon as a user message is queued", async () => {
  const h = load(); const id = h.id(await h.bash("exec sleep 20", true));
  const start = Date.now(); setTimeout(() => { h.pending.value = true; }, 300);
  expect(h.text(await h.jobs("wait", id))).toContain("new user message");
  expect(Date.now() - start).toBeLessThan(2000);
  await h.jobs("kill", id);
});
// perl prints its own PID after leaving the job's process group; the pipe stays open on its stdout.
const daemon = `perl -e 'use POSIX; setsid(); print "daemon $$\\n"; sleep 30' & sleep 0.2; echo shell-done`;
// The daemon escapes every ownership boundary by design, so tests reap it by its unique command line.
const reapDaemons = () => new Promise(resolve => spawn("pkill", ["-f", "setsid\\(\\); print \"daemon"]).once("exit", resolve));
test("a detached descendant holding the pipe does not hang kill or shutdown", async () => {
  const h = load(); const id = h.id(await h.bash(daemon, true));
  let out = ""; for (const end = Date.now() + 5000; !out.includes("shell-done") && Date.now() < end; await pause(50)) out = h.text(await h.jobs("output", id));
  const start = Date.now();
  try {
    expect(h.text(await h.jobs("kill", id))).toContain("shell-done");
    await h.shutdown();
    expect(Date.now() - start).toBeLessThan(6000);
  } finally { await reapDaemons(); }
});
test("a job reports and settles once its shell exits even if a detached descendant keeps the pipe", async () => {
  const h = load(); await h.bash(daemon, true);
  await until(() => h.messages.length > 0, 6000);
  try { expect(h.messages).toHaveLength(1); expect(h.messages[0].content).toContain("shell-done"); }
  finally { await reapDaemons(); }
});
test("reports strip terminal control sequences and binary bytes from process output", async () => {
  const h = load(); await h.bash(String.raw`printf '\033[31mred\033[0m\033]0;title\007\001\002ok'`, true);
  await until(() => h.messages.length > 0);
  const content = h.messages[0].content;
  expect(content).toContain("redok"); expect(content).not.toMatch(/[\x00-\x08\x0b\x0c\x0e-\x1f]/);
});
test("a report does not load the whole log into memory", async () => {
  const h = load({ maxJobMs: 60000 });
  await h.bash("head -c 300000000 /dev/zero | tr '\\0' 'a'", true);
  let peak = 0; const before = process.memoryUsage().rss;
  const sampler = setInterval(() => { peak = Math.max(peak, process.memoryUsage().rss - before); }, 5);
  await until(() => h.messages.length > 0, 30000); clearInterval(sampler);
  expect(h.messages).toHaveLength(1); expect(h.messages[0].content).toContain("Omitted");
  expect(peak).toBeLessThan(150_000_000);
});
test("a fast producer does not buffer its output in memory", async () => {
  const h = load({ maxJobMs: 60000 });
  let peak = 0; const before = process.memoryUsage().rss;
  const sampler = setInterval(() => { peak = Math.max(peak, process.memoryUsage().rss - before); }, 5);
  await h.bash("head -c 1000000000 /dev/zero", true);
  await until(() => h.messages.length > 0, 60000); clearInterval(sampler);
  expect(h.messages).toHaveLength(1); expect(h.messages[0].content).toContain("exit 0");
  expect(peak).toBeLessThan(300_000_000);
}, 90000);
test("foreground sleep guard reads unit suffixes", async () => {
  const h = load({ thresholdMs: 2000 });
  for (const command of ["sleep 5s", "sleep 1m", "sleep 0.1h"]) await expect(h.bash(command)).rejects.toThrow("jobs wait");
  expect(h.text(await h.bash("sleep 0.1s; printf ok"))).toBe("ok");
});
test("kill returns as soon as the group exits after SIGTERM", async () => {
  const h = load(); const id = h.id(await h.bash("exec sleep 20", true));
  const start = Date.now(); await h.jobs("kill", id);
  expect(Date.now() - start).toBeLessThan(1000);
});
test("kill racing session shutdown resolves instead of failing on the removed log", async () => {
  const h = load(); const id = h.id(await h.bash("trap '' TERM; while :; do sleep 0.1; done", true));
  const kill = h.jobs("kill", id); await pause(100); await h.shutdown();
  await expect(kill).resolves.toBeDefined();
});
test("jobs and logs die with Pi even when Pi is killed with SIGKILL", async () => {
  // A stand-in Pi process loads the extension, starts a background job that escapes its group, and is SIGKILLed.
  const marker = `${process.pid}${Date.now() % 100000}`;
  const host = spawn(process.execPath, ["-e", `
    const bg = (await import(${JSON.stringify(new URL("./index.ts", import.meta.url).href)})).default;
    const tools = new Map();
    bg({ getSettings: () => ({ bg: { thresholdMs: 40 } }), registerTool: t => tools.set(t.name, t), on: () => {}, sendMessage: () => {} });
    const ctx = { cwd: process.cwd(), mode: "rpc", hasUI: true, hasPendingMessages: () => false, sessionManager: { getSessionId: () => "t", getSessionFile: () => undefined } };
    const r = await tools.get("bash").execute("t", { command: "perl -e 'use POSIX; setsid(); exec \\"sleep\\", \\"${marker}\\"' & exec sleep ${marker}", background: true }, undefined, undefined, ctx);
    console.log(r.content[0].text.match(/Log: (\\S+)/)[1]);
  `], { stdio: ["ignore", "pipe", "inherit"] });
  let out = ""; host.stdout.on("data", c => { out += c; });
  await until(() => out.includes("\n"));
  const log = out.trim();
  const count = () => new Promise<number>(resolve => { let s = ""; const p = spawn("pgrep", ["-f", `^sleep ${marker}$`]); p.stdout.on("data", c => { s += c; }); p.once("exit", () => resolve(s.trim().split("\n").filter(Boolean).length)); });
  await until(() => false, 500);
  expect(await count()).toBe(2);
  host.kill("SIGKILL");
  let left = 2; for (const end = Date.now() + 5000; left && Date.now() < end; await pause(100)) left = await count();
  expect(left).toBe(0);
  let removed = false; for (const end = Date.now() + 3000; !removed && Date.now() < end; await pause(100)) removed = await access(log).then(() => false, () => true);
  expect(removed).toBe(true);
});
