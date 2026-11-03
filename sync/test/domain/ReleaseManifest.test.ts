import { expect, test } from "bun:test"

import { Effect, Schema, String as Str } from "effect"

import { StaticReleaseManifest } from "#domain/ReleaseManifest"

const parse = Schema.decodeUnknownEffect(StaticReleaseManifest)
const decode = (input: unknown) => Effect.runSync(parse(input))
const valid = {
  version: "1.2.3-rc_1",
  platforms: {
    "darwin-arm64": { url: "https://example.test/a", sha256: Str.repeat(64)("a"), ignored: true },
  },
  ignored: true,
}

test("decodes manifest and ignores unknown fields", () => {
  expect(decode(valid)).toEqual({
    version: valid.version,
    platforms: { "darwin-arm64": { url: "https://example.test/a", sha256: Str.repeat(64)("a") } },
  })
})

test("rejects invalid versions, checksums and payloads", () => {
  for (const version of ["", "../1", "1/2", "1 2"]) {
    expect(() => decode({ ...valid, version })).toThrow()
  }
  for (const sha256 of [Str.repeat(63)("a"), Str.repeat(64)("A"), Str.repeat(64)("g")]) {
    expect(() => decode({ ...valid, platforms: { x: { url: "x", sha256 } } })).toThrow()
  }
  expect(() => decode({ version: "1", platforms: [] })).toThrow()
})
