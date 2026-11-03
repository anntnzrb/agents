import { afterEach, expect, test } from "bun:test"
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { Effect } from "effect"

import { isIgnoredSyncEntry, isSafeManagedEntryName } from "#domain/EntryNames"
import { Files, FilesPosix, OUTPUT_MODE } from "#platform/Files"
import type { SourceContentCache } from "#platform/Files"

const { join } = path

const roots: string[] = []
const fixture = (): string => {
  const root = mkdtempSync(join(tmpdir(), "sync-files-"))
  roots.push(root)
  return root
}
afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})
const run = <A, E>(effect: Effect.Effect<A, E, Files>): Promise<A> =>
  Effect.runPromise(effect.pipe(Effect.provide(FilesPosix)))

test("entry names reject traversal and ignore transient artifacts", () => {
  for (const name of ["", ".", "..", "a/b", String.raw`a\b`, "/absolute"]) {
    expect(isSafeManagedEntryName(name)).toBe(false)
  }
  for (const name of ["file", ".hidden", "a..b"]) {
    expect(isSafeManagedEntryName(name)).toBe(true)
  }
  for (const name of [
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".DS_Store",
    ".git",
    "x.pyc",
    "x.pyo",
  ]) {
    expect(isIgnoredSyncEntry(name)).toBe(true)
  }
  expect(isIgnoredSyncEntry("x.py")).toBe(false)
})

test("managed tree prunes, preserves nested paths, and never follows destination links", async () => {
  const root = fixture()
  const dst = join(root, "dst")
  const outside = join(root, "outside")
  const src = join(root, "src")
  mkdirSync(join(src, "dir"), { recursive: true })
  mkdirSync(join(dst, "dir"), { recursive: true })
  mkdirSync(outside)
  writeFileSync(join(src, "dir", "new"), "new")
  writeFileSync(join(src, ".DS_Store"), "ignored")
  writeFileSync(join(dst, "dir", "keep"), "keep")
  writeFileSync(join(dst, "dir", "stale"), "stale")
  writeFileSync(join(outside, "safe"), "safe")
  symlinkSync(outside, join(dst, "link"))
  await run(
    Effect.gen(function* () {
      const files = yield* Files
      yield* files.syncManagedTree(src, dst, ["dir/keep"])
    }),
  )
  expect(readFileSync(join(dst, "dir", "new"), "utf8")).toBe("new")
  expect(readFileSync(join(dst, "dir", "keep"), "utf8")).toBe("keep")
  expect(() => lstatSync(join(dst, "dir", "stale"))).toThrow()
  expect(() => lstatSync(join(dst, "link"))).toThrow()
  expect(readFileSync(join(outside, "safe"), "utf8")).toBe("safe")
  expect(() => lstatSync(join(dst, ".DS_Store"))).toThrow()
})

test("children retains unrelated top-level entries but prunes synced subtrees", async () => {
  const root = fixture()
  const dst = join(root, "dst")
  const src = join(root, "src")
  mkdirSync(join(src, "d"), { recursive: true })
  mkdirSync(join(dst, "d"), { recursive: true })
  writeFileSync(join(src, "d", "new"), "new")
  writeFileSync(join(dst, "d", "old"), "old")
  writeFileSync(join(dst, "unrelated"), "keep")
  await run(
    Effect.gen(function* () {
      const files = yield* Files
      yield* files.syncManagedChildren(src, dst)
    }),
  )
  expect(readFileSync(join(dst, "unrelated"), "utf8")).toBe("keep")
  expect(() => lstatSync(join(dst, "d", "old"))).toThrow()
  expect(readFileSync(join(dst, "d", "new"), "utf8")).toBe("new")
})

test("file links are copied as files, directory links fail, and removal leaves target intact", async () => {
  const root = fixture()
  const dst = join(root, "dst")
  const src = join(root, "src")
  const target = join(root, "target")
  mkdirSync(src)
  mkdirSync(target)
  writeFileSync(join(target, "file"), "data")
  symlinkSync(join(target, "file"), join(src, "file"))
  await run(
    Effect.gen(function* () {
      const files = yield* Files
      const linked = yield* files.isSymlink(join(src, "file"))
      const absent = yield* files.isSymlink(join(src, "absent"))
      expect(linked).toBe(true)
      expect(absent).toBe(false)
      yield* files.syncManagedTree(src, dst)
    }),
  )
  expect(lstatSync(join(dst, "file")).isFile()).toBe(true)
  expect(readFileSync(join(dst, "file"), "utf8")).toBe("data")
  symlinkSync(target, join(src, "dir"))
  expect(
    await run(
      Effect.gen(function* () {
        const files = yield* Files
        return yield* Effect.flip(files.syncManagedTree(src, dst))
      }),
    ),
  ).toMatchObject({ _tag: "FilesError" })
  await run(
    Effect.gen(function* () {
      const files = yield* Files
      yield* files.rmEntry(join(src, "dir"))
      yield* files.rmEntry(join(src, "missing"))
    }),
  )
  expect(readFileSync(join(target, "file"), "utf8")).toBe("data")
})

test("file comparison checks contents and mode; atomic text preserves matching file", async () => {
  const root = fixture()
  const dst = join(root, "dst")
  const src = join(root, "src")
  writeFileSync(src, "abc")
  writeFileSync(dst, "abc")
  chmodSync(src, 0o640)
  chmodSync(dst, 0o640)
  utimesSync(dst, 1000, 1000)
  await run(
    Effect.gen(function* () {
      const files = yield* Files
      const cache: SourceContentCache = new Map()
      const identical = yield* files.isIdenticalFile(src, statSync(src), dst, cache)
      expect(identical).toBe(true)
      writeFileSync(dst, "xyz")
      utimesSync(dst, 2000, 2000)
      const changed = yield* files.isIdenticalFile(src, statSync(src), dst, cache)
      expect(changed).toBe(false)
      yield* files.syncTextFile(dst, "hello", 0o750)
      const mode = yield* files.existingFileMode(dst)
      const executable = yield* files.isExecutable(dst)
      expect(mode).toBe(0o750)
      expect(executable).toBe(true)
      const ino = statSync(dst).ino
      yield* files.syncTextFile(dst, "hello", 0o750)
      expect(statSync(dst).ino).toBe(ino)
      const missingMode = yield* files.existingFileMode(join(root, "missing"))
      expect(missingMode).toBe(OUTPUT_MODE)
    }),
  )
  expect(readFileSync(dst, "utf8")).toBe("hello")
})

test("a synced copy is trusted by metadata; editing it in place forces a restore", async () => {
  const root = fixture()
  const src = join(root, "src")
  const dst = join(root, "dst")
  mkdirSync(src)
  writeFileSync(join(src, "skill.md"), "source")
  utimesSync(join(src, "skill.md"), 1000, 1000)
  const sync = Effect.flatMap(Files, (files) => files.syncManagedTree(src, dst))
  await run(sync)
  expect(statSync(join(dst, "skill.md")).mtimeMs).toBe(1_000_000)
  writeFileSync(join(dst, "skill.md"), "edited")
  await run(sync)
  expect(readFileSync(join(dst, "skill.md"), "utf8")).toBe("source")
})
