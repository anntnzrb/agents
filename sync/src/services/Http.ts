import { Context, Effect, Layer, Schema } from "effect"
import { FetchHttpClient, HttpClient } from "effect/http"

export class HttpError extends Schema.TaggedError<HttpError, { readonly brand: unique symbol }>()(
  "HttpError",
  {
    message: Schema.String,
    url: Schema.String,
    cause: Schema.optional(Schema.Defect()),
    status: Schema.optional(Schema.Finite),
  },
) {}

export interface HttpService {
  readonly getOk: (url: string, timeoutMs: number, label: string) => Effect.Effect<Uint8Array, HttpError>
}

export class Http extends Context.Service<Http, HttpService>()("agents-sync/services/Http") {}

export const Live = Layer.effect(
  Http,
  Effect.gen(function* () {
    const client = yield* HttpClient.HttpClient
    return Http.of({
      getOk: Effect.fn("Http.getOk")(function* (url: string, timeoutMs: number, label: string) {
        const request = Effect.gen(function* () {
          const response = yield* client.get(url)
          if (response.status !== 200) {
            return { status: response.status }
          }
          const buffer = yield* response.arrayBuffer
          return { status: response.status, bytes: new Uint8Array(buffer) }
        }).pipe(
          Effect.mapError((cause) =>
            HttpError.make({
              url,
              message: `${label} (${cause.message === "" ? cause.name : cause.message})`,
              cause,
            }),
          ),
        )
        const response = yield* request.pipe(
          Effect.timeoutOrElse({
            duration: timeoutMs,
            orElse: () => Effect.fail(HttpError.make({ url, message: `${label} (timed out)` })),
          }),
        )
        if (response.status !== 200 || response.bytes === undefined) {
          return yield* HttpError.make({
            url,
            status: response.status,
            message: `${label} with HTTP ${response.status}`,
          })
        }
        return response.bytes
      }),
    })
  }),
).pipe(Layer.provide(FetchHttpClient.layer))
