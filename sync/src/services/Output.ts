import { Context, Effect, Layer, Schema } from "effect"

export class OutputError extends Schema.TaggedError<OutputError, { readonly brand: unique symbol }>()(
  "OutputError",
  {
    message: Schema.String,
    cause: Schema.Defect(),
  },
) {}

export interface OutputService {
  readonly write: (text: string) => Effect.Effect<void, OutputError>
  readonly writeError: (text: string) => Effect.Effect<void, OutputError>
  readonly err: (message: string) => Effect.Effect<void, OutputError>
  readonly warn: (message: string) => Effect.Effect<void, OutputError>
}

export class Output extends Context.Service<Output, OutputService>()("agents-sync/services/Output") {}

const writeStream = (stream: NodeJS.WriteStream, text: string) =>
  Effect.callback<undefined, OutputError>((resume) => {
    stream.write(text, (cause) => {
      resume(
        cause === undefined || cause === null
          ? Effect.undefined
          : Effect.fail(OutputError.make({ message: "output write failed", cause })),
      )
    })
  })

export const PosixLayer = Layer.succeed(
  Output,
  Output.of({
    write: Effect.fn("Output.write")((text: string) => writeStream(process.stdout, text)),
    writeError: Effect.fn("Output.writeError")((text: string) => writeStream(process.stderr, text)),
    err: Effect.fn("Output.err")((message: string) => writeStream(process.stderr, `sync: ${message}\n`)),
    warn: Effect.fn("Output.warn")((message: string) =>
      writeStream(process.stderr, `sync: warning: ${message}\n`),
    ),
  }),
)
