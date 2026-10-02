/**
 * `find`: shared semantic evidence search for codemode scripts, judged by the classifier
 * model named in the `find.classifier` setting (`"<provider>/<model id>"`).
 *
 * 1. ripgrep lists files and ranks them by query keywords.
 * 2. Bounded workers classify every eligible file's line windows.
 * 3. Full scores go to a temporary artifact; verified ranges are reported.
 *
 * Adapted from oh-my-pi's `find` (MIT, see LICENSE).
 */
import { mkdtemp, open, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";
import { Type, type ClassifierApi, type ClassifierContext, type ClassifierModel, type Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { eligible, fileScore, idf, keywords, windows } from "./search.ts";
import { renderFindCall, renderFindResult } from "./render.ts";

const WINDOW_BYTES = 2500;
const VERIFY_BATCH = 6;
const PARALLEL = 8;
/** Verified probability a range needs to be reported. */
const THRESHOLD = 0.5;

type Classifier = ClassifierModel<ClassifierApi>;
type Registry = ExtensionContext["modelRegistry"];

export type Hit = {
  path: string;
  start: number;
  end: number;
  p: number;
  snippet: string;
  text?: string;
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
  let failed = false;
  let failure: unknown;
  const worker = async () => {
    while (!failed && next < items.length) {
      try { await run(items[next++]!); }
      catch (error) { if (!failed) failure = error; failed = true; }
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, items.length) }, worker));
  if (failed) throw failure;
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
  read?: (path: string) => Promise<Buffer>;
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
  signal?.throwIfAborted();
  if (listing.code !== 0 && !(listing.code === 1 && !listing.stdout && !listing.stderr)) throw new Error(`find: rg --files failed: ${listing.stderr.trim()}`);
  const files = listing.stdout.split("\n").map(strip).filter((rel) => rel && eligible(rel));
  const weights = idf(counts, words.length, files.length);
  const ranked = files
    .map((rel) => ({ rel, lex: fileScore(counts.get(rel), weights, rel, words), name: 0 }))
    .sort((a, b) => b.lex - a.lex || (a.rel < b.rel ? -1 : 1));

  const hits: Hit[] = [];
  // Read a bounded number of files at once, and classify every passage in each.
  await pool(ranked, async ({ rel }) => {
    signal?.throwIfAborted();
    const buffer = await (options.read ?? readFile)(resolve(root, rel));
    if (buffer.includes(0)) return;
    const all = windows(buffer.toString("utf8"), WINDOW_BYTES, words, weights);
    for (let offset = 0; offset < all.length; offset += VERIFY_BATCH) {
    const passages = all.slice(offset, offset + VERIFY_BATCH);
    const ps = await ask(
      {
        state: { search: query, file: rel, ranges: passages.map((p) => ({ start: p.start, end: p.end })), passages: Object.fromEntries(passages.map((p, i) => [key(i), p.text])) },
        questions: questions(passages.length, "Does passages.$KEY substantively implement, define, or explain part of the search? Apply criteria.", {
          true: "Supplies direct evidence for an important part of the search: an implementation, definition, substantive explanation, relevant transcript statement, or log event. A helper implementing one requested step counts.",
          false: "Does not supply the requested evidence. For implementation searches, mere calls, imports, or keyword mentions do not count; for transcript, log, or documentation searches, directly relevant statements do count.",
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
    }
  });

  // Ranking affects presentation, never coverage.
  const best = new Map<string, number>();
  for (const hit of hits) best.set(hit.path, Math.max(best.get(hit.path) ?? 0, hit.p));
  const order = [...best].sort((a, b) => b[1] - a[1]).map(([path]) => path);
  return {
    hits: order.flatMap((path) => hits.filter((h) => h.path === path).sort((a, b) => b.p - a.p || a.start - b.start)),
    usage,
  };
}

export function report(query: string, hits: readonly Hit[]): string {
  if (hits.length === 0) return `No verified hits for "${query}". Rephrase, scope \`path\`, or use rg.`;
  return hits.slice(0, 16).map((h) => `${h.path}:${h.start}-${h.end}  ${h.p.toFixed(2)}  ${h.snippet}`).join("\n") + (hits.length > 16 ? `\n… ${hits.length - 16} more verified passages in the score artifact` : "");
}

export interface SearchRequest {
  query: string;
  path?: string;
}

/** Shared discovery and passage judgments for one invocation; no stale cross-run cache. */
export async function searchBatch(options: Omit<SearchOptions, "query" | "path" | "read"> & { searches: SearchRequest[] }) {
  const { searches, cwd, signal } = options;
  if (!searches.length || searches.some((s) => !s.query.trim())) throw new Error("find: provide at least one nonempty query");
  const commands = new Map<string, ReturnType<ExtensionAPI["exec"]>>();
  const reads = new Map<string, Promise<Buffer>>();
  const filesRead = new Set<string>();
  const judgments = new Map<string, Promise<number[]>>();
  const evidence = searches.map(() => new Map<string, Hit>());
  const artifact = join(await mkdtemp(join(tmpdir(), "pi-find-")), "scores.jsonl");
  const output = await open(artifact, "w");
  let writes = Promise.resolve();
  const usage: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
  let classifierRequests = 0;
  let active = 0;
  const waiting: (() => void)[] = [];
  const classify: Registry["classify"] = async (model, context) => {
    const state = context.state;
    const root = state.root as string;
    const related = searches.filter((s) => resolve(cwd, s.path ?? ".") === root);
    const identity = JSON.stringify([root, state.file, state.files, state.ranges, state.passages]);
    let promise = judgments.get(identity);
    if (!promise) {
      promise = (async () => {
        if (active >= PARALLEL) await new Promise<void>((resolve) => waiting.push(resolve));
        else active++;
        try {
          signal?.throwIfAborted();
          const entries = Object.entries(context.questions);
          const questions = Object.fromEntries(related.flatMap((s, q) => entries.map(([id, question]) => [
            `${q}_${id}`,
            { ...question, instructions: `For searches.${key(q)} only: ${question.instructions}` },
          ])));
          classifierRequests++;
          const result = await options.registry.classify(model, {
            state: { ...state, search: null, searches: Object.fromEntries(related.map((s, q) => [key(q), s.query.trim()])) },
            questions,
          }, { signal });
          if (result.usage) {
            for (const field of ["input", "output", "totalTokens"] as const) usage[field] += result.usage[field];
            usage.cost.input += result.usage.cost.input;
            usage.cost.output += result.usage.cost.output;
            usage.cost.total += result.usage.cost.total;
          }
          if (result.stopReason !== "stop") throw new Error(`find: classifier ${model.provider}/${model.id} failed: ${result.errorMessage ?? result.stopReason}`);
          return related.flatMap((_, q) => entries.map(([id]) => {
            const answer = result.answers[`${q}_${id}`];
            if (answer?.type !== "bool" || !Number.isFinite(answer.probability) || answer.probability < 0 || answer.probability > 1) throw new Error(`find: invalid classifier answer ${q}_${id}`);
            if (state.passages) {
              const passage = (state.passages as Record<string, string>)[id]!;
              const range = (state.ranges as { start: number; end: number }[])[entries.findIndex(([entry]) => entry === id)]!;
              const path = relative(cwd, resolve(root, state.file as string));
              const words = keywords(related[q]!.query);
              const line = passage.split("\n").find((line) => words.some((word) => line.toLowerCase().includes(word))) ?? passage.split("\n")[0] ?? "";
              const matches = words.map((word) => line.toLowerCase().indexOf(word)).filter((offset) => offset >= 0);
              const offset = matches.length ? Math.max(0, Math.min(...matches) - 30) : 0;
              const hit = { path, ...range, p: answer.probability, snippet: `${offset ? "…" : ""}${line.slice(offset, offset + 100).trim()}`, text: passage };
              const target = evidence[searches.indexOf(related[q]!)]!;
              const identity = JSON.stringify([path, range.start, range.end, passage]);
              writes = writes.then(async () => { await output.write(JSON.stringify({ search: searches.indexOf(related[q]!), query: related[q]!.query, ...hit }) + "\n"); });
              if (answer.probability >= THRESHOLD) target.set(identity, hit);
            }
            return answer.probability;
          }));
        } finally {
          const next = waiting.shift();
          if (next) next();
          else active--;
        }
      })();
      judgments.set(identity, promise);
    }
    const probabilities = await promise;
    judgments.delete(identity);
    const q = related.findIndex((s) => s.query.trim() === state.search);
    const ids = Object.keys(context.questions);
    return { api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(), stopReason: "stop", answers: Object.fromEntries(ids.map((id, i) => [id, { type: "bool", probability: probabilities[q * ids.length + i]! }])) };
  };
  const results: { query: string; path?: string; hits: Hit[] }[] = [];
  let complete = false;
  try {
  // Each search visits all eligible files; shared evidence is judged for every query in its scope.
  const scopes = [...new Map(searches.map((request) => [resolve(cwd, request.path ?? "."), request])).values()];
  await pool(scopes, async (request) => {
    const query = request.query.trim();
    const result = await search({
      ...options, query, path: request.path,
      registry: { classify: (model, context) => classify(model, { ...context, state: { ...context.state, root: resolve(cwd, request.path ?? ".") } }) } as Registry,
      exec: (command, args, execOptions) => {
        const id = JSON.stringify([command, args, execOptions?.cwd]);
        let pending = commands.get(id);
        if (!pending) { pending = options.exec(command, args, execOptions); commands.set(id, pending); }
        return pending;
      },
      read: (path) => {
        let pending = reads.get(path);
        if (!pending) { pending = readFile(path); reads.set(path, pending); filesRead.add(path); }
        pending.finally(() => { reads.delete(path); }).catch(() => {});
        return pending;
      },
    });
    results[searches.indexOf(request)] = { query, ...(request.path === undefined ? {} : { path: request.path }), hits: result.hits };
  });
  complete = true;
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : String(error)}; partial scores: ${artifact}`, { cause: error });
  } finally {
    await writes;
    await output.write(JSON.stringify({ type: "coverage", exhaustive: complete }) + "\n");
    await output.close();
  }
  searches.forEach((request, i) => { results[i] = { query: request.query.trim(), ...(request.path === undefined ? {} : { path: request.path }), hits: [...evidence[i]!.values()].sort((a, b) => b.p - a.p || a.path.localeCompare(b.path) || a.start - b.start) }; });
  return { results, usage, artifact, coverage: { filesRead: filesRead.size, classifierRequests, searches: searches.length, exhaustive: true } };
}

const parameters = Type.Object({
  query: Type.Optional(Type.String({ description: "Plain-language description for a single search. Use either query/path or searches, not both." })),
  path: Type.Optional(Type.String({ description: "Directory to search (default: working directory)" })),
  searches: Type.Optional(Type.Array(Type.Object({ query: Type.String(), path: Type.Optional(Type.String()) }), { minItems: 1 })),
});

export default function (pi: ExtensionAPI) {
  pi.registerTool<typeof parameters, Awaited<ReturnType<typeof searchBatch>> & { model: string; hits: Hit[] }>({
    name: "find",
    label: "Find",
    exposure: "direct",
    annotations: { readOnlyHint: true, openWorldHint: false },
    description:
      "Semantic evidence search across all eligible code, docs, logs, and transcripts in the requested directories. Use query/path or searches:[{query,path?}] for shared multi-query scoring. Returns structured hits, coverage, and a JSONL artifact containing every score, including low probabilities. Text display is capped, retrieval is not. Ignored files, binaries, and secrets are excluded. Call first when meaning is known but wording or location is not.",
    parameters,
    outputSchema: Type.Object({
      model: Type.String(),
      artifact: Type.String(),
      results: Type.Array(Type.Object({ query: Type.String(), path: Type.Optional(Type.String()), hits: Type.Array(Type.Object({ path: Type.String(), start: Type.Number(), end: Type.Number(), p: Type.Number(), snippet: Type.String(), text: Type.Optional(Type.String()) })) })),
      coverage: Type.Object({ filesRead: Type.Number(), classifierRequests: Type.Number(), searches: Type.Number(), exhaustive: Type.Boolean() }),
    }),
    renderCall(args, theme, context) {
      return renderFindCall(args, context, theme);
    },
    renderResult(result, { expanded }, theme, context) {
      const output = result.content.filter((part) => part.type === "text").map((part) => part.text).join("\n");
      if (result.details?.results?.length > 1) {
        return renderFindResult(undefined, output, { expanded, isError: context.isError }, theme);
      }
      return renderFindResult(result.details, output, {
        expanded, isError: context.isError, scope: "path" in context.args ? context.args.path : undefined, cwd: context.cwd,
      }, theme);
    },
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (params.searches ? params.query !== undefined || params.path !== undefined : !params.query?.trim()) throw new Error("find: use either query/path or searches");
      const settings = pi.getSettings() as { find?: { classifier?: unknown } };
      const model = await resolveClassifier(ctx.modelRegistry, settings.find?.classifier);
      const { results, usage, coverage, artifact } = await searchBatch({ exec: pi.exec.bind(pi), registry: ctx.modelRegistry, model, cwd: ctx.cwd, searches: params.searches ?? [{ query: params.query!, path: params.path }], signal });
      const structuredContent = { model: `${model.provider}/${model.id}`, results, coverage, artifact };
      const output = results.map((r, i) => `${results.length > 1 ? `[${i}] ${r.query} (${r.path ?? "."})\n` : ""}${report(r.query, r.hits)}`).join("\n\n");
      return { content: [{ type: "text", text: `${output}\nScores: ${artifact}` }], structuredContent, details: { ...structuredContent, usage, hits: results.flatMap((r) => r.hits) }, usage };
    },
  });
}
