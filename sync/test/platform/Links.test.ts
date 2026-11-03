import { afterEach, expect, test } from "bun:test"
import { mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import pathModule from "node:path"

import { Effect, Option } from "effect"

import { Links, LinksPosix } from "#platform/Links"

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true })
  }
})

const directory = (): string => {
  const dir = mkdtempSync(pathModule.join(tmpdir(), "sync-links-"))
  dirs.push(dir)
  return dir
}

test("reads missing and dangling links and atomically replaces targets", async () => {
  const dir = directory()
  const path = pathModule.join(dir, "current")
  await Effect.runPromise(
    Effect.gen(function* () {
      const links = yield* Links
      const missing = yield* links.readLinkTarget(path)
      expect(Option.isNone(missing)).toBe(true)
      yield* links.replaceLink(path, "missing-first")
      const first = yield* links.readLinkTarget(path)
      expect(first).toEqual(Option.some("missing-first"))
      yield* links.replaceLink(path, "../other")
      const second = yield* links.readLinkTarget(path)
      expect(second).toEqual(Option.some("../other"))
      expect(readdirSync(dir)).toEqual(["current"])
    }).pipe(Effect.provide(LinksPosix)),
  )
})

test("refuses regular files and cleans up the temporary link", async () => {
  const dir = directory()
  const path = pathModule.join(dir, "current")
  writeFileSync(path, "unmanaged")
  await Effect.runPromise(
    Effect.gen(function* () {
      const links = yield* Links
      expect((yield* Effect.result(links.readLinkTarget(path)))._tag).toBe("Failure")
      expect((yield* Effect.result(links.replaceLink(path, "target")))._tag).toBe("Failure")
      expect(readFileSync(path, "utf8")).toBe("unmanaged")
      expect(readdirSync(dir)).toEqual(["current"])
    }).pipe(Effect.provide(LinksPosix)),
  )
})

test("reads an existing relative symlink verbatim", async () => {
  const dir = directory()
  const path = pathModule.join(dir, "current")
  symlinkSync("../version", path)
  const target = await Effect.runPromise(
    Effect.gen(function* () {
      const links = yield* Links
      return yield* links.readLinkTarget(path)
    }).pipe(Effect.provide(LinksPosix)),
  )
  expect(target).toEqual(Option.some("../version"))
})
