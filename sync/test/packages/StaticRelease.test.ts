import { afterEach, expect, test } from "bun:test"
import { createHash } from "node:crypto"
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { BunServices } from "@effect/platform-bun"
import { Effect, Layer, Option } from "effect"

import type { StaticRelease } from "#domain/HarnessAdapters"
import { currentStaticRelease, prepareStaticRelease, refreshStaticRelease } from "#packages/StaticRelease"
import { Host } from "#platform/Host"
import { LinksPosix } from "#platform/Links"
import { LockPosix } from "#platform/Lock"
import { Http, HttpError } from "#services/Http"
import { Output } from "#services/Output"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const spec: StaticRelease = {
  manifestUrl: "https://example.test/manifest",
  installSegments: ["install"],
  executableSegments: ["bin", "tool"],
  targets: { "linux-x64": "linux" },
  manSegments: ["man"],
  manDestSegments: ["man"],
}

test("installs, rotates and reuses releases; failed refresh preserves current and preparation falls back", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "static-release-"))
  roots.push(home)
  const source = path.join(home, "source")
  mkdirSync(path.join(source, "bin"), { recursive: true })
  mkdirSync(path.join(source, "man"))
  writeFileSync(path.join(source, "bin", "tool"), "#!/bin/sh\n")
  chmodSync(path.join(source, "bin", "tool"), 0o755)
  writeFileSync(path.join(source, "man", "tool.1"), "manual")
  const archivePath = path.join(home, "bundle.tar.gz")
  const tar = Bun.spawnSync(["tar", "-czf", archivePath, "-C", source, "."])
  expect(tar.exitCode).toBe(0)
  const archive = readFileSync(archivePath)
  const sha = createHash("sha256").update(archive).digest("hex")
  let version = "1.0.0"
  let fail = false
  let downloads = 0
  const host = Host.of({
    platform: "linux",
    arch: "x64",
    home,
    cacheHome: home,
    uid: 1,
    pid: 1,
    env: {},
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(true),
  })
  const http = Http.of({
    getOk: (url) => {
      if (fail) {
        return Effect.fail(HttpError.make({ url, message: "offline" }))
      }
      if (url === spec.manifestUrl) {
        return Effect.succeed(
          new TextEncoder().encode(
            `{"version":"${version}","platforms":{"linux":{"url":"https://example.test/archive","sha256":"${sha}"}}}`,
          ),
        )
      }
      downloads++
      return Effect.succeed(archive)
    },
  })
  const output = Output.of({ write: () => Effect.void, err: () => Effect.void, warn: () => Effect.void })
  const layer = Layer.mergeAll(
    BunServices.layer,
    LinksPosix,
    LockPosix,
    Layer.succeed(Host, host),
    Layer.succeed(Http, http),
    Layer.succeed(Output, output),
  )
  const prepare = () =>
    Effect.runPromise(prepareStaticRelease(spec, home, 10_000).pipe(Effect.provide(layer)))
  const first = await prepare()
  expect(first).toBe(path.join(home, "install/_versions/1.0.0/bin/tool"))
  expect(readFileSync(path.join(home, "install/_versions/1.0.0/distribution"), "utf8")).toBe("curl-bash\n")
  expect(readlinkSync(path.join(home, "man/tool.1"))).toBe(
    path.join(home, "install/_versions/current/man/tool.1"),
  )
  await prepare()
  expect(downloads).toBe(1)
  version = "2.0.0"
  const refreshed = await Effect.runPromise(
    refreshStaticRelease(spec, home, 10_000).pipe(Effect.provide(layer)),
  )
  expect(refreshed).toBe(true)
  expect(readlinkSync(path.join(home, "install/_versions/previous"))).toBe("1.0.0")
  fail = true
  const fallback = await prepare()
  expect(fallback).toBe(realpathSync(path.join(home, "install/_versions/2.0.0/bin/tool")))
  const failureResult = await Effect.runPromise(
    Effect.result(refreshStaticRelease(spec, home, 10_000)).pipe(Effect.provide(layer)),
  )
  expect(failureResult._tag).toBe("Failure")
})

test("current cache rejects links outside a direct numeric version", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "static-release-"))
  roots.push(home)
  const versions = path.join(home, "install/_versions")
  mkdirSync(versions, { recursive: true })
  const outside = path.join(home, "outside")
  mkdirSync(path.join(outside, "bin"), { recursive: true })
  writeFileSync(path.join(outside, "bin/tool"), "bad", { mode: 0o755 })
  symlinkSync(outside, path.join(versions, "current"))
  const value = await Effect.runPromise(
    currentStaticRelease(spec, home).pipe(Effect.provide(BunServices.layer)),
  )
  expect(Option.isNone(value)).toBe(true)
})

test("rejects an archive containing an escaping symbolic link", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "static-release-"))
  roots.push(home)
  const source = path.join(home, "source")
  mkdirSync(source)
  symlinkSync("../../outside", path.join(source, "escape"))
  const archivePath = path.join(home, "bad.tar.gz")
  const tar = Bun.spawnSync(["tar", "-czf", archivePath, "-C", source, "."])
  expect(tar.exitCode).toBe(0)
  const archive = readFileSync(archivePath)
  const sha256 = createHash("sha256").update(archive).digest("hex")
  const manifest = new TextEncoder().encode(
    `{"version":"1.0.0","platforms":{"linux":{"url":"archive","sha256":"${sha256}"}}}`,
  )
  const http = Http.of({ getOk: (url) => Effect.succeed(url === spec.manifestUrl ? manifest : archive) })
  const host = Host.of({
    platform: "linux",
    arch: "x64",
    home,
    cacheHome: home,
    uid: 1,
    pid: 1,
    env: {},
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(true),
  })
  const output = Output.of({ write: () => Effect.void, err: () => Effect.void, warn: () => Effect.void })
  const layer = Layer.mergeAll(
    BunServices.layer,
    LinksPosix,
    LockPosix,
    Layer.succeed(Host, host),
    Layer.succeed(Http, http),
    Layer.succeed(Output, output),
  )
  const failureResult = await Effect.runPromise(
    Effect.result(refreshStaticRelease(spec, home, 10_000)).pipe(Effect.provide(layer)),
  )
  expect(failureResult._tag).toBe("Failure")
  const result = await Effect.runPromise(
    currentStaticRelease(spec, home).pipe(Effect.provide(BunServices.layer)),
  )
  expect(result).toEqual(Option.none())
})

test("reports malformed JSON separately from an invalid manifest", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "static-release-"))
  roots.push(home)
  let body = "{"
  const host = Host.of({
    platform: "linux",
    arch: "x64",
    home,
    cacheHome: home,
    uid: 1,
    pid: 1,
    env: {},
    now: Effect.succeed(0),
    isPidAlive: () => Effect.succeed(true),
  })
  const http = Http.of({ getOk: () => Effect.succeed(new TextEncoder().encode(body)) })
  const output = Output.of({ write: () => Effect.void, err: () => Effect.void, warn: () => Effect.void })
  const layer = Layer.mergeAll(
    BunServices.layer,
    LinksPosix,
    LockPosix,
    Layer.succeed(Host, host),
    Layer.succeed(Http, http),
    Layer.succeed(Output, output),
  )
  const first = await Effect.runPromise(
    Effect.result(refreshStaticRelease(spec, home, 10_000)).pipe(Effect.provide(layer)),
  )
  expect(first._tag).toBe("Failure")
  if (first._tag === "Failure") {
    expect(first.failure.message).toBe("release manifest parse failed")
  }
  body = "{}"
  const second = await Effect.runPromise(
    Effect.result(refreshStaticRelease(spec, home, 10_000)).pipe(Effect.provide(layer)),
  )
  expect(second._tag).toBe("Failure")
  if (second._tag === "Failure") {
    expect(second.failure.message).toBe("invalid release manifest")
  }
})
