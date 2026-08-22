#!/usr/bin/env bun
import { BunRuntime, BunServices } from "@effect/platform-bun";
import { Effect, Option } from "effect";
import { Argument, Command, Flag } from "effect/unstable/cli";
import { discoverActiveOmpProviders } from "#config";
import { executeSingleSearch, resolveOmp } from "#executor";
import { mergeParallelResults } from "#merge";
import type { SearchResult } from "#models";

export const searchCommand = Command.make(
  "omp-search",
  {
    query: Argument.string("query").pipe(
      Argument.withDescription("Search query words"),
      Argument.variadic({ min: 1 })
    ),
    provider: Flag.string("provider").pipe(
      Flag.withDescription("Explicit single OMP provider name"),
      Flag.optional
    ),
    providers: Flag.string("providers").pipe(
      Flag.withDescription(
        "Comma-separated list of providers to query concurrently (defaults to OMP's configured active providers)"
      ),
      Flag.optional
    ),
    single: Flag.boolean("single").pipe(
      Flag.withDescription("Force single-provider auto-fallback chain instead of parallel fan-out"),
      Flag.withDefault(false)
    ),
    recency: Flag.choice("recency", ["day", "week", "month", "year"]).pipe(
      Flag.withDescription("Recency filter (day, week, month, year)"),
      Flag.optional
    ),
    limit: Flag.integer("limit").pipe(
      Flag.withDescription("Number of sources per provider (minimum 2; defaults to 2)"),
      Flag.withDefault(2)
    ),
    full: Flag.boolean("full").pipe(
      Flag.withDescription("Request the complete OMP answer instead of compact output"),
      Flag.withDefault(false)
    ),
    includeRaw: Flag.boolean("include-raw").pipe(
      Flag.withDescription("Include ANSI-stripped raw OMP output for debugging"),
      Flag.withDefault(false)
    ),
    timeout: Flag.float("timeout").pipe(
      Flag.withDescription("Outer timeout in seconds (default: 300)"),
      Flag.withDefault(300)
    ),
    ompBin: Flag.string("omp-bin").pipe(
      Flag.withDescription("OMP executable path; defaults to OMP_BIN or omp on PATH"),
      Flag.optional
    ),
  },
  (config) =>
    Effect.gen(function* () {
      const ompBinCandidate = Option.getOrUndefined(config.ompBin);
      const binaryResult = yield* resolveOmp(ompBinCandidate).pipe(
        Effect.map((bin) => ({ ok: true as const, binary: bin })),
        Effect.catchTag("OmpBinaryNotFoundError", (err) =>
          Effect.succeed({ ok: false as const, message: err.message })
        )
      );

      if (!binaryResult.ok) {
        process.stderr.write(`omp-search: ${binaryResult.message}\n`);
        process.exit(127);
      }

      const binary = binaryResult.binary;
      const fallbackQuery = config.query.join(" ");
      const explicitProvider = Option.getOrUndefined(config.provider);
      const explicitProviders = Option.getOrUndefined(config.providers);

      let providerList: (string | undefined)[];
      if (explicitProvider) {
        providerList = [explicitProvider];
      } else if (explicitProviders) {
        providerList = explicitProviders
          .split(",")
          .map((p) => p.trim())
          .filter(Boolean);
      } else if (config.single) {
        providerList = [undefined];
      } else {
        const discovered = yield* discoverActiveOmpProviders();
        providerList = discovered.length > 0 ? [...discovered] : [undefined];
      }

      const singleExecutionOptions = {
        queryWords: config.query,
        recency: Option.getOrUndefined(config.recency),
        limit: config.limit,
        full: config.full,
        includeRaw: config.includeRaw,
        timeoutSeconds: config.timeout,
        ompBin: ompBinCandidate,
      };

      let finalPayload: SearchResult;

      if (providerList.length === 1) {
        finalPayload = yield* executeSingleSearch(
          {
            ...singleExecutionOptions,
            provider: providerList[0],
          },
          binary
        );
      } else {
        const effects = providerList.map((p) =>
          executeSingleSearch(
            {
              ...singleExecutionOptions,
              provider: p,
            },
            binary
          )
        );

        const results = yield* Effect.all(effects, { concurrency: "unbounded" });
        finalPayload = mergeParallelResults(fallbackQuery, results, !config.full);
      }

      process.stdout.write(JSON.stringify(finalPayload) + "\n");
      if (finalPayload.exit_code !== 0) {
        process.exit(finalPayload.exit_code);
      }
    })
).pipe(
  Command.withDescription("Run OMP search and emit an agent-shaped JSON envelope.")
);

export const runCli = (args: readonly string[]) =>
  Command.runWith(searchCommand, { version: "1.0.0" })(args).pipe(
    Effect.provide(BunServices.layer)
  );

if (import.meta.main) {
  BunRuntime.runMain(runCli(process.argv.slice(2)));
}
