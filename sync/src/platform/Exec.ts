import { Context, Effect, Layer, Schema } from "effect"

export interface ExecPlan {
  readonly executable: string
  readonly args: readonly string[]
  readonly env: Readonly<Record<string, string>>
}

export class ExecError extends Schema.TaggedError<ExecError, { readonly brand: unique symbol }>()(
  "ExecError",
  {
    executable: Schema.String,
    message: Schema.String,
    cause: Schema.Defect(),
  },
) {}

export interface ExecService {
  readonly exec: (plan: ExecPlan) => Effect.Effect<never, ExecError>
}

export class Exec extends Context.Service<Exec, ExecService>()("agents-sync/platform/Exec") {}

export const PosixLayer = Layer.succeed(
  Exec,
  Exec.of({
    exec: Effect.fn("Exec.exec")(function* (plan: ExecPlan) {
      for (const stream of [process.stdout, process.stderr]) {
        yield* Effect.callback<undefined, ExecError>((resume) => {
          stream.write("", (cause) => {
            resume(
              cause === undefined || cause === null
                ? Effect.undefined
                : Effect.fail(
                    ExecError.make({ executable: plan.executable, message: "failed to flush output", cause }),
                  ),
            )
          })
        })
      }
      return yield* Effect.try({
        try: () => {
          if (process.execve === undefined) {
            throw new Error("process.execve is unavailable")
          }
          return process.execve(plan.executable, [plan.executable, ...plan.args], plan.env)
        },
        catch: (cause) =>
          ExecError.make({ executable: plan.executable, message: `exec ${plan.executable} failed`, cause }),
      })
    }),
  }),
)
