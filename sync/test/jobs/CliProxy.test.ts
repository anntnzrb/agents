import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunFileSystem } from "@effect/platform-bun"
import { Effect, Layer } from "effect"
import { FetchHttpClient } from "effect/http"

import {
  isCliproxyTargetReady,
  publishCliproxyEndpointTemplates,
  syncCliproxyEndpointTemplate,
} from "#jobs/CliProxy"
import { FilesPosix } from "#platform/Files"

const { join } = path
const live = Layer.mergeAll(FilesPosix, BunFileSystem.layer, FetchHttpClient.layer)

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const deployment = { gateway: { base_url: "http://localhost:8317/v1" } }
const rootDir = () => {
  const root = mkdtempSync(join(tmpdir(), "cliproxy-"))
  roots.push(root)
  return root
}
test("renders templates and preserves requested TOML sections", async () => {
  const root = rootDir()
  const src = join(root, "source")
  const dst = join(root, "dest")
  writeFileSync(src, `url = "\${CLIPROXY_CLIENT_BASE_URL}"\n`)
  writeFileSync(dst, '[local]\nkey = "value"\n')
  await Effect.runPromise(
    syncCliproxyEndpointTemplate(src, dst, deployment, ["local"]).pipe(Effect.provide(live)),
  )
  expect(readFileSync(dst, "utf8")).toBe('url = "http://localhost:8317/v1"\n\n[local]\nkey = "value"\n')
})
test("publication rolls back earlier files when a later source is missing", async () => {
  const root = rootDir()
  const src = join(root, "source")
  const dst = join(root, "dest")
  writeFileSync(src, `url = "\${CLIPROXY_CLIENT_BASE_URL}"\n`)
  writeFileSync(dst, "old\n")
  const targets = [
    { src, dst, preserveTopLevels: [] },
    { src: join(root, "missing"), dst: join(root, "other"), preserveTopLevels: [] },
  ]
  const program = publishCliproxyEndpointTemplates(targets, deployment, { skipReadiness: true })
  const result = await Effect.runPromise(Effect.flip(program).pipe(Effect.provide(live)))
  expect(result).toBeDefined()
  expect(readFileSync(dst, "utf8")).toBe("old\n")
})
test("readiness requests models with no-cache headers and requires data", async () => {
  let headers: Headers | undefined
  const server = Bun.serve({
    port: 0,
    fetch(request) {
      headers = request.headers
      return Response.json({ data: [{ id: "model" }] })
    },
  })
  try {
    const settings = { gateway: { base_url: `${server.url.origin}/v1` } }
    const ready = await Effect.runPromise(
      isCliproxyTargetReady(settings).pipe(Effect.provide(FetchHttpClient.layer)),
    )
    expect(ready).toBe(true)
    expect(headers?.get("accept")).toBe("application/json")
    expect(headers?.get("cache-control")).toBe("no-cache")
  } finally {
    await server.stop(true)
  }
})
