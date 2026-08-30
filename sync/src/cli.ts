#!/usr/bin/env bun

import { launchMain, main } from "@core/index.ts";
import { BunRuntime, BunServices } from "@effect/platform-bun";
import { Effect } from "effect";
import { Argument, Command, Flag } from "effect/unstable/cli";

const syncHandler = ({ refreshModels }: { readonly refreshModels: boolean }) =>
  Effect.promise(async () => {
    const exitCode = await main({ forceModelRefresh: refreshModels });
    if (exitCode !== 0) {
      process.exit(exitCode);
    }
  });

const syncCommand = Command.make(
  "sync",
  {
    refreshModels: Flag.boolean("refresh-models").pipe(Flag.withDefault(false)),
  },
  syncHandler,
);

const launchCommand = Command.make(
  "launch",
  {
    target: Argument.string("target"),
  },
  ({ target }) =>
    Effect.promise(async () => {
      const rawArgs = Bun.argv.slice(2);
      const targetIndex = rawArgs.indexOf("launch");
      const subArgs = targetIndex >= 0 ? rawArgs.slice(targetIndex + 2) : [];
      const separatorIndex = subArgs.indexOf("--");
      const forwardedArgs = separatorIndex >= 0 ? subArgs.slice(separatorIndex + 1) : subArgs;
      const exitCode = await launchMain(target, forwardedArgs);
      process.exit(exitCode);
    }),
);

const rootCommand = Command.make(
  "agents-sync",
  {
    refreshModels: Flag.boolean("refresh-models").pipe(Flag.withDefault(false)),
  },
  syncHandler,
).pipe(Command.withSubcommands([syncCommand, launchCommand]));

const rawArgs = Bun.argv.slice(2);

// Fast-path trampoline launch:
if (rawArgs[0] === "launch") {
  const sourceName = rawArgs[1];
  const separator = rawArgs[2];
  if (!sourceName || (separator !== "--" && separator !== undefined)) {
    console.error("sync: usage: launch NAME -- [ARGS...]");
    process.exit(2);
  }
  process.exit(await launchMain(sourceName, rawArgs.slice(separator ? 3 : 2)));
}

// Effect-powered Sync CLI:
if (rawArgs.length === 0 || rawArgs[0] === "sync" || rawArgs[0]?.startsWith("-")) {
  const cliArgs = rawArgs[0] === "sync" ? rawArgs.slice(1) : rawArgs;
  if (cliArgs.some((arg) => arg !== "--refresh-models" && !arg.startsWith("-"))) {
    console.error("sync: usage: sync [--refresh-models]");
    process.exit(2);
  }
  const program = Command.runWith(rootCommand, { version: "1.0.0" })(rawArgs);
  BunRuntime.runMain(program.pipe(Effect.provide(BunServices.layer)));
} else {
  console.error(`sync: unknown command: ${rawArgs[0]}`);
  process.exit(2);
}
