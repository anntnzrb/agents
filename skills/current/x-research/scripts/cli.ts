#!/usr/bin/env bun
import { BunHttpClient, BunRuntime, BunServices } from "@effect/platform-bun";
import { Effect, Option } from "effect";
import { Argument, Command, Flag } from "effect/unstable/cli";
import {
  CliError,
  ContractError,
  FeedChoice,
  ProviderError,
  RankingChoice,
  SCHEMA_VERSION,
} from "#models";
import { FxTwitterClientLive } from "#provider";
import { runCommand } from "#commands";
import { summaryData } from "#summary";

const KNOWN_COMMANDS: Record<string, true> = {
  fetch: true,
  "user-posts": true,
  search: true,
  conversation: true,
};

function getCommandHint(args: readonly string[]): string {
  for (const arg of args) {
    if (arg in KNOWN_COMMANDS) {
      return arg;
    }
  }
  return "unknown";
}

function emitSuccess(command: string, data: Record<string, unknown>, pretty: boolean): void {
  const envelope = {
    ok: true,
    schema_version: SCHEMA_VERSION,
    command,
    data,
  };
  const serialized = pretty ? JSON.stringify(envelope, null, 2) : JSON.stringify(envelope);
  process.stdout.write(serialized + "\n");
}

function emitFailure(
  command: string,
  error: { code: string; message: string; details: Record<string, unknown> },
  pretty: boolean
): void {
  const envelope = {
    ok: false,
    schema_version: SCHEMA_VERSION,
    command,
    error: {
      code: error.code,
      message: error.message,
      details: error.details,
    },
  };
  const serialized = pretty ? JSON.stringify(envelope, null, 2) : JSON.stringify(envelope);
  process.stderr.write(serialized + "\n");
}

const fetchCommand = Command.make(
  "fetch",
  {
    target: Argument.string("target").pipe(
      Argument.withDescription("numeric Post ID or an x.com/twitter.com status URL")
    ),
    provider: Flag.string("provider").pipe(
      Flag.withDescription("read-only provider (only fxtwitter is supported)"),
      Flag.withDefault("fxtwitter")
    ),
    lang: Flag.string("lang").pipe(
      Flag.withDescription("optional translation language"),
      Flag.optional
    ),
    summary: Flag.boolean("summary").pipe(
      Flag.withDescription("project output to citation-safe fields without metrics or media"),
      Flag.withDefault(false)
    ),
    pretty: Flag.boolean("pretty").pipe(
      Flag.withDescription("emit valid JSON with two-space indentation"),
      Flag.withDefault(false)
    ),
  },
  (args) =>
    Effect.gen(function* () {
      const data = yield* runCommand({
        command: "fetch",
        target: args.target,
        provider: args.provider,
        lang: Option.getOrUndefined(args.lang),
        summary: args.summary,
        pretty: args.pretty,
      });
      const finalData = args.summary ? summaryData("fetch", data) : data;
      emitSuccess("fetch", finalData, args.pretty);
    })
).pipe(Command.withDescription("fetch one exact public post"));

const userPostsCommand = Command.make(
  "user-posts",
  {
    handle: Argument.string("handle").pipe(
      Argument.withDescription("X handle without the @ prefix")
    ),
    count: Flag.integer("count").pipe(
      Flag.withDescription("requested number of posts (1..100)"),
      Flag.withDefault(20)
    ),
    cursor: Flag.string("cursor").pipe(
      Flag.withDescription("optional pagination cursor"),
      Flag.optional
    ),
    includeReplies: Flag.boolean("include-replies").pipe(
      Flag.withDescription("include replies in the timeline request"),
      Flag.withDefault(false)
    ),
    summary: Flag.boolean("summary").pipe(
      Flag.withDescription("project output to citation-safe fields without metrics or media"),
      Flag.withDefault(false)
    ),
    pretty: Flag.boolean("pretty").pipe(
      Flag.withDescription("emit valid JSON with two-space indentation"),
      Flag.withDefault(false)
    ),
  },
  (args) =>
    Effect.gen(function* () {
      const data = yield* runCommand({
        command: "user-posts",
        handle: args.handle,
        count: args.count,
        cursor: Option.getOrUndefined(args.cursor),
        includeReplies: args.includeReplies,
        summary: args.summary,
        pretty: args.pretty,
      });
      const finalData = args.summary ? summaryData("user-posts", data) : data;
      emitSuccess("user-posts", finalData, args.pretty);
    })
).pipe(Command.withDescription("fetch one bounded user timeline page"));

const searchCommand = Command.make(
  "search",
  {
    query: Argument.string("query").pipe(
      Argument.withDescription("search query; whitespace is normalized")
    ),
    count: Flag.integer("count").pipe(
      Flag.withDescription("requested number of posts (1..100)"),
      Flag.withDefault(30)
    ),
    feed: Flag.choice("feed", ["latest", "top", "media"]).pipe(
      Flag.withDescription("search feed"),
      Flag.withDefault("latest")
    ),
    cursor: Flag.string("cursor").pipe(
      Flag.withDescription("optional pagination cursor"),
      Flag.optional
    ),
    summary: Flag.boolean("summary").pipe(
      Flag.withDescription("project output to citation-safe fields without metrics or media"),
      Flag.withDefault(false)
    ),
    pretty: Flag.boolean("pretty").pipe(
      Flag.withDescription("emit valid JSON with two-space indentation"),
      Flag.withDefault(false)
    ),
  },
  (args) =>
    Effect.gen(function* () {
      const data = yield* runCommand({
        command: "search",
        query: args.query,
        count: args.count,
        feed: args.feed as FeedChoice,
        cursor: Option.getOrUndefined(args.cursor),
        summary: args.summary,
        pretty: args.pretty,
      });
      const finalData = args.summary ? summaryData("search", data) : data;
      emitSuccess("search", finalData, args.pretty);
    })
).pipe(Command.withDescription("fetch one bounded search page"));

const conversationCommand = Command.make(
  "conversation",
  {
    id: Argument.string("id").pipe(Argument.withDescription("numeric post ID")),
    rankingMode: Flag.choice("ranking-mode", ["likes", "recency"]).pipe(
      Flag.withDescription("reply ranking mode"),
      Flag.withDefault("likes")
    ),
    cursor: Flag.string("cursor").pipe(
      Flag.withDescription("optional pagination cursor"),
      Flag.optional
    ),
    summary: Flag.boolean("summary").pipe(
      Flag.withDescription("project output to citation-safe fields without metrics or media"),
      Flag.withDefault(false)
    ),
    pretty: Flag.boolean("pretty").pipe(
      Flag.withDescription("emit valid JSON with two-space indentation"),
      Flag.withDefault(false)
    ),
  },
  (args) =>
    Effect.gen(function* () {
      const data = yield* runCommand({
        command: "conversation",
        id: args.id,
        rankingMode: args.rankingMode as RankingChoice,
        cursor: Option.getOrUndefined(args.cursor),
        summary: args.summary,
        pretty: args.pretty,
      });
      const finalData = args.summary ? summaryData("conversation", data) : data;
      emitSuccess("conversation", finalData, args.pretty);
    })
).pipe(Command.withDescription("fetch one conversation page"));

export const xResearchCommand = Command.make("x-research").pipe(
  Command.withSubcommands([fetchCommand, userPostsCommand, searchCommand, conversationCommand]),
  Command.withDescription("Read public X/Twitter posts through the FxTwitter v2 API.")
);

export const runCli = (rawArgs: readonly string[]) => {
  const isHelp = rawArgs.includes("--help") || rawArgs.includes("-h");
  const isPretty = rawArgs.includes("--pretty");
  const hint = getCommandHint(rawArgs);

  const cliProgram = Command.runWith(xResearchCommand, {
    version: "1.0.0",
    renderErrors: false,
  })(rawArgs).pipe(
    Effect.provide(FxTwitterClientLive),
    Effect.provide(BunHttpClient.layer),
    Effect.provide(BunServices.layer)
  );

  return cliProgram.pipe(
    Effect.catchIf(
      () => true,
      (err: unknown) =>
        Effect.sync(() => {
          if (isHelp) {
            process.exit(0);
          }
          if (err instanceof CliError) {
            emitFailure(hint, err, isPretty);
            process.exit(2);
          }
          if (err instanceof ProviderError || err instanceof ContractError) {
            emitFailure(hint, err, isPretty);
            process.exit(1);
          }
          // General CLI / Argument / Flag parsing error from effect/cli
          const message = err instanceof Error ? err.message : String(err);
          emitFailure(
            hint,
            {
              code: "usage",
              message,
              details: {},
            },
            isPretty
          );
          process.exit(2);
        })
    ),
    Effect.catchDefect((defect: unknown) =>
      Effect.sync(() => {
        if (defect instanceof CliError) {
          emitFailure(hint, defect, isPretty);
          process.exit(2);
        }
        if (defect instanceof ProviderError || defect instanceof ContractError) {
          emitFailure(hint, defect, isPretty);
          process.exit(1);
        }
        const message = defect instanceof Error ? defect.message : String(defect);
        emitFailure(
          hint,
          {
            code: "internal_error",
            message,
            details: {},
          },
          isPretty
        );
        process.exit(1);
      })
    )
  );
};

if (import.meta.main) {
  BunRuntime.runMain(runCli(process.argv.slice(2)));
}
