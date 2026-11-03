import { BunRuntime, BunServices } from "@effect/platform-bun"
import { Cause, Effect, Exit, Layer, Option, Predicate, Runtime } from "effect"
import { FetchHttpClient } from "effect/http"

import { runCli } from "#cli/Cli"
import { PosixLayer as ExecLayer } from "#platform/Exec"
import { FilesPosix } from "#platform/Files"
import { PosixLayer as HostLayer } from "#platform/Host"
import { LinksPosix } from "#platform/Links"
import { LockPosix } from "#platform/Lock"
import { Proc } from "#platform/Proc"
import { RunningExecutables } from "#platform/RunningExecutables"
import { Live as HttpLayer } from "#services/Http"
import { PosixLayer as OutputLayer } from "#services/Output"
import { Live as SyncEnvLive } from "#services/SyncEnv"

const EXIT_TIMED_OUT = 124

const platform = Layer.mergeAll(
  BunServices.layer,
  ExecLayer,
  FilesPosix,
  HostLayer,
  LinksPosix,
  LockPosix,
  Proc.layer,
  OutputLayer,
  HttpLayer,
  FetchHttpClient.layer,
)
const app = Layer.mergeAll(RunningExecutables.layer, SyncEnvLive).pipe(Layer.provideMerge(platform))

// The program's success value is the process exit code. A deadline cleanup overrun
// forces 124 even though interrupted work may still be unwinding.
const teardown: Runtime.Teardown = (exit, onExit) => {
  if (Exit.isSuccess(exit) && typeof exit.value === "number") {
    onExit(exit.value)
    return
  }
  if (Exit.isFailure(exit)) {
    const error = Cause.findErrorOption(exit.cause)
    if (Option.isSome(error) && Predicate.isTagged(error.value, "DeadlineCleanupOverrun")) {
      onExit(EXIT_TIMED_OUT)
      return
    }
  }
  Runtime.defaultTeardown(exit, onExit)
}

BunRuntime.runMain(runCli(process.argv.slice(2)).pipe(Effect.provide(app)), { teardown })
