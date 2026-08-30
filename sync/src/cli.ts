#!/usr/bin/env bun

import { launchMain, main } from "@core/index.ts";
import { BunRuntime, BunServices } from "@effect/platform-bun";
import { Console, Effect, Exit } from "effect";

const program = Effect.gen(function* () {
  const rawArgs = Bun.argv.slice(2);

  if (rawArgs[0] === "launch") {
    const sourceName = rawArgs[1];
    const separator = rawArgs[2];
    if (!sourceName || (separator !== "--" && separator !== undefined)) {
      yield* Console.error("sync: usage: launch NAME -- [ARGS...]");
      return 2;
    }
    return yield* Effect.promise(() => launchMain(sourceName, rawArgs.slice(separator ? 3 : 2)));
  }

  const cliArgs = rawArgs[0] === "sync" ? rawArgs.slice(1) : rawArgs;
  if (cliArgs.some((arg) => arg !== "--refresh-models" && !arg.startsWith("-"))) {
    yield* Console.error("sync: usage: sync [--refresh-models]");
    return 2;
  }

  if (cliArgs.some((arg) => arg.startsWith("-") && arg !== "--refresh-models")) {
    yield* Console.error("sync: usage: sync [--refresh-models]");
    return 2;
  }

  const forceModelRefresh = cliArgs.includes("--refresh-models");
  return yield* Effect.promise(() => main({ forceModelRefresh }));
});

BunRuntime.runMain(program.pipe(Effect.provide(BunServices.layer)), {
  teardown: (exit, onExit) => {
    if (Exit.isSuccess(exit) && typeof exit.value === "number") {
      onExit(exit.value);
    } else if (Exit.isFailure(exit)) {
      onExit(1);
    } else {
      onExit(0);
    }
  },
});
