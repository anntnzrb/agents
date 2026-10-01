import { afterEach, expect, test } from "bun:test";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type { ClassifierContext, ClassifierResult } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { report, resolveClassifier, search } from "./index.ts";
import { eligible, keywords, selectWindows, windows } from "./search.ts";

const directories: string[] = [];
afterEach(async () => {
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

const run = promisify(execFile);
const exec: ExtensionAPI["exec"] = async (command, args, options) => {
  try {
    const { stdout, stderr } = await run(command, args, { cwd: options?.cwd, signal: options?.signal });
    return { stdout, stderr, code: 0, killed: false };
  } catch (error) {
    const e = error as { stdout?: string; stderr?: string; code?: number };
    return { stdout: e.stdout ?? "", stderr: e.stderr ?? "", code: typeof e.code === "number" ? e.code : 1, killed: false };
  }
};

async function workspace(files: Record<string, string>) {
  const cwd = await mkdtemp(join(tmpdir(), "pi-find-test-"));
  directories.push(cwd);
  for (const [rel, text] of Object.entries(files)) {
    await mkdir(join(cwd, rel, ".."), { recursive: true });
    await writeFile(join(cwd, rel), text);
  }
  return cwd;
}

const MODELS = [
  { provider: "acme", id: "judge/v1" },
  { provider: "acme", id: "broken" },
  { provider: "other", id: "nocreds" },
];

/** Fake registry: answers each bool question with `judge(state, id)`; `acme/broken` returns errors. */
function registry(judge: (state: ClassifierContext["state"], id: string) => number) {
  const calls: string[] = [];
  const fake = {
    getModelOfType: (_type: string, provider: string, id: string) => MODELS.find((m) => m.provider === provider && m.id === id),
    getAvailableOfType: async (_type: string, provider?: string) => MODELS.filter((m) => m.provider === (provider ?? m.provider) && m.provider !== "other"),
    classify: async (model: { provider: string; id: string }, context: ClassifierContext): Promise<ClassifierResult> => {
      calls.push(`${model.provider}/${model.id}`);
      const base = { api: "fake", provider: model.provider, model: model.id, timestamp: 0 };
      if (model.id === "broken") return { ...base, answers: {}, stopReason: "error", errorMessage: "402 funds" };
      const answers = Object.fromEntries(
        Object.keys(context.questions).map((id) => [id, { type: "bool" as const, probability: judge(context.state, id) }]),
      );
      const usage = { input: 10, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 11, cost: { input: 0.01, output: 0, cacheRead: 0, cacheWrite: 0, total: 0.01 } };
      return { ...base, answers, usage, stopReason: "stop" };
    },
  };
  return { calls, registry: fake as unknown as ExtensionContext["modelRegistry"] };
}

const signal = new AbortController().signal;

test("resolveClassifier reads <provider>/<id> and rejects missing, unknown, or unauthenticated models", async () => {
  const { registry: fake } = registry(() => 1);
  expect(await resolveClassifier(fake, "acme/judge/v1")).toEqual(MODELS[0]!);
  expect(resolveClassifier(fake, undefined)).rejects.toThrow('"classifier": "<provider>/<model id>"');
  expect(resolveClassifier(fake, "acme/")).rejects.toThrow("<provider>/<model id>");
  expect(resolveClassifier(fake, "acme/nope")).rejects.toThrow("unknown classifier model acme/nope");
  expect(resolveClassifier(fake, "other/nocreds")).rejects.toThrow("has no credentials");
});

test("keywords keep quoted phrases, stem tokens, and drop stopwords", () => {
  expect(keywords('where "rate limit" retries are scheduled')).toEqual(["rate limit", "retri", "schedul"]);
});

test("eligible skips lockfiles, build output, binaries, and secrets", () => {
  expect(eligible("src/retry.ts")).toBe(true);
  for (const rel of ["bun.lock", "node_modules/x/index.js", "dist/a.js", "logo.png", ".env", "certs/server.pem"]) {
    expect(eligible(rel)).toBe(false);
  }
});

test("windows cover every line once and selection keeps file order", () => {
  const text = Array.from({ length: 50 }, (_, i) => (i === 40 ? "retry here" : `line ${i}`)).join("\n");
  const passages = windows(text, 64, ["retry"], [1]);
  expect(passages[0]!.start).toBe(1);
  expect(passages.at(-1)!.end).toBe(50);
  passages.slice(1).forEach((p, i) => expect(p.start).toBe(passages[i]!.end + 1));
  const kept = selectWindows(passages, 3);
  expect(kept.some((p) => p.text.includes("retry here"))).toBe(true);
  expect(kept.map((p) => p.start)).toEqual([...kept.map((p) => p.start)].sort((a, b) => a - b));
});

test("search reports only verified ranges with the configured model and sums usage", async () => {
  const cwd = await workspace({
    "src/retry.ts": "export function scheduleRetry(attempt: number) {\n  return 2 ** attempt * 100; // backoff\n}\n",
    "src/retry.test.ts": "test('retry backoff', () => scheduleRetry(1));\n",
    "docs/notes.md": "We talk about retry backoff here.\n",
    "bun.lock": "retry backoff",
  });
  const { calls, registry: fake } = registry((state, id) => {
    if (!state.passages) return 0.5;
    return (state.passages as Record<string, string>)[id]!.includes("2 ** attempt") ? 0.92 : 0.1;
  });
  const { hits, usage } = await search({ exec, registry: fake, model: MODELS[0]!, cwd, query: "exponential retry backoff", signal });
  expect(new Set(calls)).toEqual(new Set(["acme/judge/v1"]));
  expect(hits).toEqual([{ path: "src/retry.ts", start: 1, end: 3, p: 0.92, snippet: "export function scheduleRetry(attempt: number) {" }]);
  expect(usage.cost.total).toBeCloseTo(0.01 * calls.length);
  expect(report("q", hits)).toBe("src/retry.ts:1-3  0.92  export function scheduleRetry(attempt: number) {");
  expect(report("q", [])).toStartWith('No verified hits for "q"');
});

test("search fails on the first classifier error instead of returning partial results", async () => {
  const cwd = await workspace({ "a.ts": "retry" });
  const { registry: fake } = registry(() => 1);
  expect(search({ exec, registry: fake, model: MODELS[1]!, cwd, query: "retry", signal })).rejects.toThrow("acme/broken failed: 402 funds");
});

test("search scopes to path and reports paths relative to cwd", async () => {
  const cwd = await workspace({ "pkg/a/retry.ts": "retry()\n", "pkg/b/retry.ts": "retry()\n" });
  const { registry: fake } = registry(() => 0.8);
  const { hits } = await search({ exec, registry: fake, model: MODELS[0]!, cwd, query: "retry", path: "pkg/a", signal });
  expect(hits.map((h) => h.path)).toEqual(["pkg/a/retry.ts"]);
});
