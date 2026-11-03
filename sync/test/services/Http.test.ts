import { describe, expect, test } from "bun:test"

import { Effect } from "effect"

import { Http, Live } from "#services/Http"

const get = (url: string, timeoutMs = 1000) =>
  Effect.runPromise(
    Effect.gen(function* () {
      const http = yield* Http
      return yield* http.getOk(url, timeoutMs, "download failed")
    }).pipe(Effect.provide(Live)),
  )

describe("Http", () => {
  test("follows redirects and returns response bytes", async () => {
    const server = Bun.serve({
      port: 0,
      fetch(request) {
        return new URL(request.url).pathname === "/redirect"
          ? Response.redirect(new URL("/body", request.url).href, 302)
          : new Response(new Uint8Array([0, 255, 42]))
      },
    })
    try {
      expect([...(await get(`${server.url.href}redirect`))]).toEqual([0, 255, 42])
    } finally {
      await server.stop(true)
    }
  })

  test("rejects non-200 responses with the label and status", async () => {
    const server = Bun.serve({ port: 0, fetch: () => new Response(null, { status: 204 }) })
    try {
      expect(await get(server.url.href).catch(String)).toContain("download failed with HTTP 204")
    } finally {
      await server.stop(true)
    }
  })

  test("reports transport failures", async () => {
    expect(await get("not a url").catch(String)).toContain("download failed")
  })
  test("times out while waiting for the response", async () => {
    const server = Bun.serve({
      port: 0,
      async fetch(request) {
        const { promise, resolve } = Promise.withResolvers<undefined>()
        request.signal.addEventListener(
          "abort",
          () => {
            resolve(undefined)
          },
          { once: true },
        )
        await promise
        return new Response(null)
      },
    })
    try {
      expect(await get(server.url.href, 20).catch(String)).toContain("download failed (timed out)")
    } finally {
      await server.stop(true)
    }
  })
})
