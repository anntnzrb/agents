#!/usr/bin/env bun

import { launchMain, main } from "@core/index.ts";
import { BunRuntime, BunServices } from "@effect/platform-bun";
import { Console, Effect, Exit } from "effect";

const HELP_TEXT = `sync — Reconcile AI agent configurations, skills, and harness environments from SSOT.

Usage:
  sync [sync]
  sync launch <name> [-- <args...>]
  sync -h | --help | help

Commands:
  sync (default)
    Reconciles harness configurations, instruction files (HARNESS.md),
    skills, tools, secrets, and generated launch wrappers (~/.local/bin).

  launch <name> [-- <args...>]
    Runs best-effort reconciliation, prepares the harness or tool package,
    and executes it with any forwarded arguments.

Options:
  -h, --help, help    Show this help message.
`;

const isHelpFlag = (arg: string | undefined): boolean =>
  arg === "-h" || arg === "--help" || arg === "help";

const program = Effect.gen(function* () {
  const rawArgs = Bun.argv.slice(2);

  if (rawArgs.length === 1 && isHelpFlag(rawArgs[0])) {
    yield* Console.log(HELP_TEXT.trimEnd());
    return 0;
  }

  if (rawArgs[0] === "launch") {
    if (isHelpFlag(rawArgs[1])) {
      yield* Console.log(
        `Usage: sync launch <name> [-- <args...>]\n\nLaunch a managed harness or tool by name with optional forwarded arguments.`,
      );
      return 0;
    }
    const sourceName = rawArgs[1];
    const separator = rawArgs[2];
    if (!sourceName || (separator !== "--" && separator !== undefined)) {
      yield* Console.error("sync: usage: launch NAME -- [ARGS...]");
      return 2;
    }
    return yield* Effect.promise(() => launchMain(sourceName, rawArgs.slice(separator ? 3 : 2)));
  }

  const cliArgs = rawArgs[0] === "sync" ? rawArgs.slice(1) : rawArgs;
  if (cliArgs.length === 1 && isHelpFlag(cliArgs[0])) {
    yield* Console.log(HELP_TEXT.trimEnd());
    return 0;
  }
  if (cliArgs.length > 0) {
    yield* Console.error("sync: usage: sync\nRun 'sync --help' for available commands.");
    return 2;
  }

  return yield* Effect.promise(() => main());
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
