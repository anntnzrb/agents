import { Effect } from "effect"

import { job } from "#programs/Jobs"
import { launch } from "#programs/Launch"
import { syncMain } from "#programs/RunSync"
import { update } from "#programs/Update"
import { Output } from "#services/Output"

import { parseCli } from "./Parse"
import type { CliCommand } from "./Parse"

const dispatch = Effect.fn("Cli.dispatch")(function* (
  command: Exclude<CliCommand, { readonly _tag: "Help" | "Usage" }>,
) {
  switch (command._tag) {
    case "Sync": {
      return yield* syncMain()
    }
    case "Update": {
      return yield* update()
    }
    case "Launch": {
      return yield* launch(command.name, command.args)
    }
    case "Job": {
      return yield* job(command.name)
    }
  }
})

export const runCli = Effect.fn("Cli.runCli")(function* (args: readonly string[]) {
  const command = parseCli(args)
  const output = yield* Output
  if (command._tag === "Help") {
    yield* output.write(command.text)
    return 0
  }
  if (command._tag === "Usage") {
    yield* output.writeError(command.text)
    return 2
  }
  // Expected failures print once as `sync: <message>` and exit 1; a deadline cleanup
  // overrun keeps its tag so the process boundary can force exit 124.
  return yield* dispatch(command).pipe(
    Effect.catchIf(
      (error) => error._tag !== "DeadlineCleanupOverrun",
      (error) => output.err(error.message).pipe(Effect.as(1)),
    ),
  )
})
