import { BunRuntime, BunServices } from "@effect/platform-bun"
import { Effect } from "effect"

const program = Effect.log("sync-ts scaffold")

BunRuntime.runMain(program.pipe(Effect.provide(BunServices.layer)))
