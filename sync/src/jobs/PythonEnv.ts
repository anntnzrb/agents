import { Effect, FileSystem, Path, String as Str } from "effect"

import { Proc } from "#platform/Proc"
import { Output } from "#services/Output"

export const ensurePythonEnv = Effect.fn("PythonEnv.ensurePythonEnv")(function* (
  home: string,
  segments: readonly string[],
  timeoutMs: number,
) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const proc = yield* Proc
  const output = yield* Output
  const venvDir = path.join(home, ...segments)
  if (yield* fs.exists(path.join(venvDir, "bin", "python"))) {
    return
  }
  if (!(yield* proc.commandExists("uv"))) {
    yield* output.warn("uv not found; skipping python-env bootstrap.")
    return
  }
  const options = { timeoutMs }
  const install = yield* proc.run(["uv", "python", "install"], options)
  if (install.timedOut || install.outputLimited || install.exitCode !== 0) {
    yield* output.warn("uv python install failed; skipping.")
    return
  }
  const find = yield* proc.run(["uv", "python", "find"], options)
  const latest = Str.trim(find.stdout)
  if (find.outputLimited || latest === "") {
    yield* output.warn("uv python find returned empty; skipping.")
    return
  }
  const venv = yield* proc.run(["uv", "venv", "--python", latest, venvDir], options)
  if (venv.timedOut || venv.outputLimited || venv.exitCode !== 0) {
    yield* output.warn("failed to create python-env")
  }
})
