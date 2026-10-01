/**
 * `find`: semantic code search for codemode scripts, judged by the classifier
 * model named in the `find.classifier` setting (`"<provider>/<model id>"`).
 *
 * 1. ripgrep lists files and ranks them by query keywords.
 * 2. The classifier judges the top candidates by path.
 * 3. The classifier verifies line windows of the best files; only verified ranges are reported.
 *
 * Adapted from oh-my-pi's `find` (MIT, see LICENSE).
 */
import { readFile, stat } from "node:fs/promises";
import { relative, resolve } from "node:path";
import { Type, type ClassifierApi, type ClassifierContext, type ClassifierModel, type Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { eligible, fileScore, idf, keywords, selectWindows, windows } from "./search.ts";

const CANDIDATES = 96;
const NAME_BATCH = 48;
const FILES = 12;
const WINDOWS_PER_FILE = 8;
const WINDOW_BYTES = 2500;
const VERIFY_BATCH = 6;
const PARALLEL = 8;
/** Verified probability a range needs to be reported. */
const THRESHOLD = 0.5;
const MAX_HITS = 8;
const RANGES_PER_HIT = 2;

type Classifier = ClassifierModel<ClassifierApi>;
type Registry = ExtensionContext["modelRegistry"];

export interface Hit {
  path: string;
  start: number;
  end: number;
  p: number;
  snippet: string;
}

/**
 * The classifier named by `find.classifier`; the model id may contain `/`.
 * @throws when the setting is missing, unknown, or lacks credentials.
 */
export async function resolveClassifier(registry: Registry, setting: unknown): Promise<Classifier> {
  const ref = typeof setting === "string" ? setting.trim() : "";
  const slash = ref.indexOf("/");
  if (slash <= 0 || slash === ref.length - 1) {
    throw new Error('find needs a classifier model: set "find": { "classifier": "<provider>/<model id>" } in Pi settings');
  }
  const [provider, id] = [ref.slice(0, slash), ref.slice(slash + 1)];
  if (!registry.getModelOfType("classifier", provider, id)) throw new Error(`find: unknown classifier model ${ref}`);
  const model = (await registry.getAvailableOfType("classifier", provider)).find((m) => m.id === id);
  if (!model) throw new Error(`find: classifier model ${ref} has no credentials`);
  return model;
}

/** Run `run` over `items` with at most {@link PARALLEL} in flight. */
async function pool<T>(items: readonly T[], run: (item: T) => Promise<void>): Promise<void> {
  let next = 0;
  const worker = async () => {
    while (next < items.length) await run(items[next++]!);
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, items.length) }, worker));
}

/** One `bool` question per item, keyed `k000`, `k001`, …; the `state` entries use the same keys. */
const key = (i: number) => `k${String(i).padStart(3, "0")}`;
function questions(count: number, instructions: string, criteria: { true: string; false: string }) {
  return Object.fromEntries(Array.from({ length: count }, (_, i) => [key(i), { type: "bool" as const, instructions: instructions.replace("$KEY", key(i)), criteria }]));
}

export interface SearchOptions {
  exec: ExtensionAPI["exec"];
  registry: Registry;
  model: Classifier;
  cwd: string;
  query: string;
  path?: string;
  signal?: AbortSignal;
}

/** @throws on the first classifier failure: a partial search would hide coverage loss. */
export async function search(options: SearchOptions): Promise<{ hits: Hit[]; usage: Usage }> {
  const { exec, registry, model, cwd, query, signal } = options;
  const root = resolve(cwd, options.path ?? ".");
  if (!(await stat(root).catch(() => undefined))?.isDirectory()) throw new Error(`find: not a directory: ${options.path}`);
  const usage: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
  const ask = async (context: ClassifierContext, count: number): Promise<number[]> => {
    const result = await registry.classify(model, context, { signal });
    if (result.usage) {
      for (const field of ["input", "output", "totalTokens"] as const) usage[field] += result.usage[field];
      usage.cost.input += result.usage.cost.input;
      usage.cost.output += result.usage.cost.output;
      usage.cost.total += result.usage.cost.total;
    }
    if (result.stopReason !== "stop") throw new Error(`find: classifier ${model.provider}/${model.id} failed: ${result.errorMessage ?? result.stopReason}`);
    return Array.from({ length: count }, (_, i) => {
      const answer = result.answers[key(i)];
      return answer?.type === "bool" ? answer.probability : 0;
    });
  };

  // Lexical prior: one ripgrep count per keyword, IDF-weighted. The explicit `.` stops rg reading a piped stdin.
  const strip = (rel: string) => rel.replace(/^\.\//, "");
  const words = keywords(query);
  const counts = new Map<string, number[]>();
  const [listing] = await Promise.all([
    exec("rg", ["--files", "."], { cwd: root, signal }),
    ...words.map(async (word, k) => {
      const result = await exec("rg", ["--count-matches", "--null", "-i", "-F", "-e", word, "."], { cwd: root, signal });
      for (const line of result.stdout.split("\n")) {
        const [rel, n] = line.split("\0");
        if (!rel || n === undefined) continue;
        const row = counts.get(strip(rel)) ?? words.map(() => 0);
        row[k] = Number(n) || 0;
        counts.set(strip(rel), row);
      }
    }),
  ]);
  if (listing.code !== 0) throw new Error(`find: rg --files failed: ${listing.stderr.trim()}`);
  const files = listing.stdout.split("\n").map(strip).filter((rel) => rel && eligible(rel));
  const weights = idf(counts, words.length, files.length);
  const ranked = files
    .map((rel) => ({ rel, lex: fileScore(counts.get(rel), weights, rel, words), name: 0 }))
    .sort((a, b) => b.lex - a.lex || (a.rel < b.rel ? -1 : 1))
    .slice(0, CANDIDATES);

  // Wave 1: judge candidates by path.
  const batches = Array.from({ length: Math.ceil(ranked.length / NAME_BATCH) }, (_, b) => ranked.slice(b * NAME_BATCH, (b + 1) * NAME_BATCH));
  await pool(batches, async (batch) => {
    const ps = await ask(
      {
        state: { search: query, files: Object.fromEntries(batch.map((f, i) => [key(i), f.rel])) },
        questions: questions(batch.length, "Is file $KEY likely to contain code or text matching the search? Judge by its path.", {
          true: "Plausibly contains a matching implementation or definition",
          false: "Unrelated by name and location",
        }),
      },
      batch.length,
    );
    batch.forEach((f, i) => (f.name = ps[i]!));
  });
  // The two strongest lexical files are always read; the rest follow the path judgment.
  const selected = new Set(ranked.slice(0, 2).map((f) => f.rel));
  for (const f of [...ranked].sort((a, b) => b.name - a.name || b.lex - a.lex)) {
    if (selected.size >= FILES) break;
    selected.add(f.rel);
  }

  // Wave 2: verify the strongest windows of each selected file.
  const jobs = (
    await Promise.all(
      [...selected].map(async (rel) => {
        const buffer = await readFile(resolve(root, rel)).catch(() => undefined);
        if (!buffer || buffer.subarray(0, 8192).includes(0)) return [];
        const passages = selectWindows(windows(buffer.toString("utf8"), WINDOW_BYTES, words, weights), WINDOWS_PER_FILE);
        return Array.from({ length: Math.ceil(passages.length / VERIFY_BATCH) }, (_, b) => ({ rel, passages: passages.slice(b * VERIFY_BATCH, (b + 1) * VERIFY_BATCH) }));
      }),
    )
  ).flat();
  const hits: Hit[] = [];
  await pool(jobs, async ({ rel, passages }) => {
    const ps = await ask(
      {
        state: { search: query, file: rel, passages: Object.fromEntries(passages.map((p, i) => [key(i), p.text])) },
        questions: questions(passages.length, "Does passages.$KEY substantively implement, define, or explain part of the search? Apply criteria.", {
          true: "Contains an implementation, definition, or substantive explanation of an important part of the search. A helper implementing one requested step counts.",
          false: "Only mentions, calls, imports, tests, or configures the subject, or is unrelated code sharing keywords.",
        }),
      },
      passages.length,
    );
    passages.forEach((passage, i) => {
      if (ps[i]! < THRESHOLD) return;
      const lines = passage.text.split("\n");
      const line = lines.find((l) => words.some((w) => l.toLowerCase().includes(w))) ?? lines.find((l) => l.trim()) ?? "";
      hits.push({ path: relative(cwd, resolve(root, rel)), start: passage.start, end: passage.end, p: ps[i]!, snippet: line.trim().slice(0, 100) });
    });
  });

  // Strongest files first, at most RANGES_PER_HIT ranges each.
  const best = new Map<string, number>();
  for (const hit of hits) best.set(hit.path, Math.max(best.get(hit.path) ?? 0, hit.p));
  const order = [...best].sort((a, b) => b[1] - a[1]).slice(0, MAX_HITS).map(([path]) => path);
  return {
    hits: order.flatMap((path) => hits.filter((h) => h.path === path).sort((a, b) => b.p - a.p || a.start - b.start).slice(0, RANGES_PER_HIT)),
    usage,
  };
}

export function report(query: string, hits: readonly Hit[]): string {
  if (hits.length === 0) return `No verified hits for "${query}". Rephrase, scope \`path\`, or use rg.`;
  return hits.map((h) => `${h.path}:${h.start}-${h.end}  ${h.p.toFixed(2)}  ${h.snippet}`).join("\n");
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "find",
    label: "Find",
    // Reached only through codemode scripts, so the description carries all usage guidance.
    exposure: "codemode",
    annotations: { readOnlyHint: true, openWorldHint: false },
    description:
      "Semantic code search: describe a behavior in plain language, get `path:start-end probability snippet` lines for the code that implements it, strongest first, verified by a classifier. Call it first, before rg or grep, when you can describe a behavior but don't know the identifier or file, then read the returned ranges. Use rg only for known strings or symbols. No hits is weak evidence of absence: confirm with rg before concluding.",
    parameters: Type.Object({
      query: Type.String({ description: "Plain-language description of the behavior, e.g. 'retry backoff for failed uploads'. Quote exact phrases or identifiers." }),
      path: Type.Optional(Type.String({ description: "Directory to search (default: working directory)" })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const query = params.query.trim();
      if (!query) throw new Error("find: query must describe what to find");
      const settings = pi.getSettings() as { find?: { classifier?: unknown } };
      const model = await resolveClassifier(ctx.modelRegistry, settings.find?.classifier);
      const { hits, usage } = await search({ exec: pi.exec.bind(pi), registry: ctx.modelRegistry, model, cwd: ctx.cwd, query, path: params.path, signal });
      return { content: [{ type: "text", text: report(query, hits) }], details: { model: `${model.provider}/${model.id}`, hits }, usage };
    },
  });
}
